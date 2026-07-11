from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import validate_release as release_validation
from scripts.validate_release import (
    RELEASE_BRANCH,
    ReleaseValidationError,
    validate_final_history,
    validate_tracked_file_types,
)


def _initialize_release_repository(path: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "release@example.invalid"], cwd=path, check=True)
    (path / "README.md").write_text("Release tree\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "Accepted-paper reproducibility release"], cwd=path, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=path, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", head], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", "."], cwd=path, check=True)
    subprocess.run(["git", "tag", "-a", "v1.0.0", "-m", "Accepted-paper reproducibility release"], cwd=path, check=True)
    return head


def test_final_history_accepts_single_clean_root_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    head = _initialize_release_repository(tmp_path)
    original_run = subprocess.run

    def reject_network_git(command: list[str], *args: object, **kwargs: object):
        if command[:2] == ["git", "ls-remote"]:
            raise AssertionError("final release validation attempted network access")
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(release_validation.subprocess, "run", reject_network_git)
    validate_final_history(tmp_path, legacy_merge_base="f" * 40)

    with pytest.raises(ReleaseValidationError, match="Legacy merge base remains an ancestor"):
        validate_final_history(tmp_path, legacy_merge_base=head)


def test_final_history_rejects_lightweight_or_unreviewed_tag_annotation(tmp_path: Path) -> None:
    _initialize_release_repository(tmp_path)
    subprocess.run(["git", "tag", "-d", "v1.0.0"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "tag", "v1.0.0"], cwd=tmp_path, check=True)
    with pytest.raises(ReleaseValidationError, match="must be an annotated tag"):
        validate_final_history(tmp_path, legacy_merge_base="f" * 40)

    subprocess.run(["git", "tag", "-d", "v1.0.0"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "tag", "-a", "v1.0.0", "-m", "Prepared by " + "OpenAI"],
        cwd=tmp_path,
        check=True,
    )
    with pytest.raises(ReleaseValidationError, match="annotation must exactly match"):
        validate_final_history(tmp_path, legacy_merge_base="f" * 40)


def test_final_history_rejects_multiple_commits_and_release_branch(tmp_path: Path) -> None:
    _initialize_release_repository(tmp_path)
    subprocess.run(["git", "branch", RELEASE_BRANCH], cwd=tmp_path, check=True)
    with pytest.raises(ReleaseValidationError, match="Stale release reference remains"):
        validate_final_history(tmp_path, legacy_merge_base="f" * 40)

    subprocess.run(["git", "branch", "-D", RELEASE_BRANCH], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("Second commit\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "Update release tree"], cwd=tmp_path, check=True)
    with pytest.raises(ReleaseValidationError, match="exactly one root commit"):
        validate_final_history(tmp_path, legacy_merge_base="f" * 40)


def test_release_validation_rejects_tracked_symlink(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    outside = tmp_path.parent / "outside-release-file.txt"
    outside.write_text("not public\n", encoding="utf-8")
    (tmp_path / "linked.txt").symlink_to(outside)
    subprocess.run(["git", "add", "linked.txt"], cwd=tmp_path, check=True)

    with pytest.raises(ReleaseValidationError, match="not a regular file"):
        validate_tracked_file_types(tmp_path)
