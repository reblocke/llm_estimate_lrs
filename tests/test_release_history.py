from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import validate_release as release_validation
from scripts.git_safety import no_lazy_fetch_environment
from scripts.validate_contracts import ContractValidationError
from scripts.validate_metadata import STAGE2_REQUIRED_PATHS, MetadataValidationError
from scripts.validate_release import (
    RELEASE_BRANCH,
    ReleaseValidationError,
    materialized_candidate,
    validate_candidate_checksums,
    validate_documentation,
    validate_final_history,
    validate_release_candidate,
    validate_required_paths,
    validate_tracked_file_types,
)

ROOT = Path(__file__).resolve().parents[1]


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


def _initialize_candidate_repository(path: Path) -> tuple[str, str]:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "release@example.invalid"], cwd=path, check=True)
    (path / "candidate.txt").write_text("candidate A\n", encoding="utf-8")
    subprocess.run(["git", "add", "candidate.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "Candidate A"], cwd=path, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=path, check=True)
    candidate_a = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (path / "candidate.txt").write_text("governance B\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "Governance B"], cwd=path, check=True)
    governance_b = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return candidate_a, governance_b


def _future_contract(path: Path, release_ref: str = "v2.0.0") -> dict[str, object]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "release_ref": release_ref,
        "audited_commit": head,
        "audited_tree": tree,
        "required_paths": sorted(STAGE2_REQUIRED_PATHS),
        "history_policy": {
            "complete_history_required": True,
            "annotated_tag_required": True,
            "tag_message": "Future reproducibility release",
            "parentless_release_commit_required": False,
            "single_root_required": False,
            "candidate_default_branch_tag_parity_required": True,
            "default_branch_ref": "refs/heads/main",
            "forbidden_refs": [],
            "forbidden_ancestors": [],
            "allowed_refs": {
                "namespace": "refs/heads",
                "values": ["refs/heads/main"],
            },
            "allowed_tags": [f"refs/tags/{release_ref}"],
        },
        "immutable_prior_tags": [],
    }


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


def test_final_history_accepts_policy_driven_ordinary_future_history(tmp_path: Path) -> None:
    _initialize_release_repository(tmp_path)
    (tmp_path / "README.md").write_text("Future release tree\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "Prepare future release"], cwd=tmp_path, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", head], cwd=tmp_path, check=True)
    subprocess.run(["git", "tag", "-d", "v1.0.0"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "tag", "-a", "v2.0.0", "-m", "Future reproducibility release"], cwd=tmp_path, check=True)
    contract = {
        "release_ref": "v2.0.0",
        "audited_commit": head,
        "audited_tree": tree,
        "history_policy": {
            "complete_history_required": True,
            "annotated_tag_required": True,
            "tag_message": "Future reproducibility release",
            "parentless_release_commit_required": False,
            "single_root_required": False,
            "candidate_default_branch_tag_parity_required": True,
            "default_branch_ref": "refs/remotes/origin/main",
            "forbidden_refs": [],
            "forbidden_ancestors": [],
            "allowed_refs": {
                "namespace": "refs/remotes/origin",
                "values": ["refs/remotes/origin/HEAD", "refs/remotes/origin/main"],
            },
            "allowed_tags": ["refs/tags/v2.0.0"],
        },
        "immutable_prior_tags": [],
    }

    validate_final_history(tmp_path, contract=contract, candidate_ref="HEAD")


def test_prepare_and_final_apply_distinct_tag_contexts(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "release@example.invalid"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("Future candidate\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "Future candidate"], cwd=tmp_path, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=tmp_path, check=True)
    contract = _future_contract(tmp_path)
    head = contract["audited_commit"]

    validate_final_history(
        tmp_path,
        contract=contract,
        candidate_ref=head,
        context="prepare",
    )
    with pytest.raises(ReleaseValidationError, match="release tag.*does not exist|Could not resolve"):
        validate_final_history(
            tmp_path,
            contract=contract,
            candidate_ref=head,
            context="final",
        )

    subprocess.run(["git", "tag", "v2.0.0"], cwd=tmp_path, check=True)
    with pytest.raises(ReleaseValidationError, match="annotated tag"):
        validate_final_history(
            tmp_path,
            contract=contract,
            candidate_ref=head,
            context="final",
        )
    with pytest.raises(ReleaseValidationError, match="absent"):
        validate_final_history(
            tmp_path,
            contract=contract,
            candidate_ref=head,
            context="prepare",
        )

    subprocess.run(["git", "tag", "-d", "v2.0.0"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "tag", "-a", "v2.0.0", "-m", "Wrong message"],
        cwd=tmp_path,
        check=True,
    )
    with pytest.raises(ReleaseValidationError, match="annotation"):
        validate_final_history(
            tmp_path,
            contract=contract,
            candidate_ref=head,
            context="final",
        )

    subprocess.run(["git", "tag", "-d", "v2.0.0"], cwd=tmp_path, check=True, capture_output=True)
    other_commit = subprocess.run(
        ["git", "commit-tree", contract["audited_tree"], "-p", head, "-m", "Other commit"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "tag", "-a", "v2.0.0", "-m", "Future reproducibility release", other_commit],
        cwd=tmp_path,
        check=True,
    )
    with pytest.raises(ReleaseValidationError, match="does not resolve to audited_commit"):
        validate_final_history(
            tmp_path,
            contract=contract,
            candidate_ref=head,
            context="final",
        )

    subprocess.run(["git", "tag", "-d", "v2.0.0"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "tag", "-a", "v2.0.0", "-m", "Future reproducibility release"],
        cwd=tmp_path,
        check=True,
    )
    validate_final_history(
        tmp_path,
        contract=contract,
        candidate_ref=head,
        context="final",
    )


def test_prepare_rejects_wrong_candidate_commit_and_contracted_tree(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "release@example.invalid"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("Contracted candidate\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "Contracted candidate"], cwd=tmp_path, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=tmp_path, check=True)
    contract = _future_contract(tmp_path)
    contracted_commit = contract["audited_commit"]

    (tmp_path / "README.md").write_text("Wrong candidate\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "Wrong candidate"], cwd=tmp_path, check=True)
    wrong_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    with pytest.raises(ReleaseValidationError, match="does not match audited_commit"):
        validate_final_history(
            tmp_path,
            contract=contract,
            candidate_ref=wrong_commit,
            context="prepare",
        )

    wrong_tree_contract = dict(contract)
    wrong_tree_contract["audited_tree"] = "0" * 40
    with pytest.raises(ReleaseValidationError, match="Audited release tree"):
        validate_final_history(
            tmp_path,
            contract=wrong_tree_contract,
            candidate_ref=contracted_commit,
            context="prepare",
        )


def test_prepare_and_final_accept_the_same_release_ready_metadata() -> None:
    contract = json.loads((ROOT / "release/contracts/v1.0.0.json").read_text(encoding="utf-8"))

    validate_documentation("prepare", contract)
    validate_documentation("final", contract)


def test_release_candidate_checks_materialized_ref_not_governance_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_a, governance_b = _initialize_candidate_repository(tmp_path)
    observed_roots: list[Path] = []
    history_rechecks: list[tuple[str, str]] = []

    def assert_candidate_root(root: Path) -> None:
        observed_roots.append(root)
        assert (root / "candidate.txt").read_text(encoding="utf-8") == "candidate A\n"

    def fake_contract(
        _path: Path,
        repository: Path,
        **kwargs: object,
    ) -> dict[str, object]:
        assert repository == tmp_path
        assert kwargs["context"] == "prepare"
        assert kwargs["candidate_ref"] == candidate_a
        candidate_root = kwargs["current_files_root"]
        assert isinstance(candidate_root, Path)
        assert_candidate_root(candidate_root)
        return {"required_paths": sorted(STAGE2_REQUIRED_PATHS)}

    def fake_data(root: Path) -> dict[str, object]:
        assert_candidate_root(root)
        return {"dataset": {"rows": 700}}

    def fake_metadata(
        root: Path,
        *,
        schema_root: Path,
    ) -> dict[str, object]:
        assert_candidate_root(root)
        assert schema_root == tmp_path
        return {"data_sources": 31}

    def fake_manifest(root: Path) -> dict[str, object]:
        assert_candidate_root(root)
        return {"manifest_id": "test-manifest"}

    def fake_file_type_validation(
        _repository: Path,
        *,
        tree: str,
        files_root: Path,
    ) -> None:
        assert tree
        assert_candidate_root(files_root)

    monkeypatch.setattr(release_validation, "validate_release_contract", fake_contract)
    monkeypatch.setattr(release_validation, "validate_data", fake_data)
    monkeypatch.setattr(release_validation, "validate_metadata_contracts", fake_metadata)
    monkeypatch.setattr(
        release_validation,
        "validate_tracked_file_types",
        fake_file_type_validation,
    )
    monkeypatch.setattr(
        release_validation,
        "validate_required_paths",
        lambda _contract, root: assert_candidate_root(root),
    )
    monkeypatch.setattr(
        release_validation,
        "validate_candidate_checksums",
        lambda root, **_kwargs: (assert_candidate_root(root), 1)[1],
    )
    monkeypatch.setattr(release_validation, "validate_notebooks", assert_candidate_root)
    monkeypatch.setattr(release_validation, "validate_manifest", fake_manifest)
    monkeypatch.setattr(
        release_validation,
        "validate_documentation",
        lambda _mode, _contract, root: assert_candidate_root(root),
    )
    monkeypatch.setattr(
        release_validation,
        "validate_history_policy",
        lambda _contract, _repository, *, context, candidate_ref: history_rechecks.append(
            (context, candidate_ref)
        ),
    )

    summary = validate_release_candidate(
        Path("governance-contract.json"),
        mode="prepare",
        candidate_ref=candidate_a,
        repository=tmp_path,
    )

    current_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert current_head == governance_b
    assert summary["candidate_commit"] == candidate_a
    assert summary["candidate_checksum_entries"] == 1
    assert summary["candidate_tree"] == subprocess.run(
        ["git", "rev-parse", f"{candidate_a}^{{tree}}"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert observed_roots
    assert history_rechecks == [("prepare", candidate_a)]
    assert all(not root.exists() for root in observed_roots)


def test_release_candidate_validates_stage2_metadata_from_materialized_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_a, _governance_b = _initialize_candidate_repository(tmp_path)
    observed_root: Path | None = None

    monkeypatch.setattr(
        release_validation,
        "validate_release_contract",
        lambda *_args, **_kwargs: {"required_paths": sorted(STAGE2_REQUIRED_PATHS)},
    )
    monkeypatch.setattr(
        release_validation,
        "validate_tracked_file_types",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        release_validation,
        "validate_required_paths",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        release_validation,
        "validate_candidate_checksums",
        lambda *_args, **_kwargs: 1,
    )
    monkeypatch.setattr(release_validation, "validate_data", lambda _root: {})
    monkeypatch.setattr(release_validation, "validate_notebooks", lambda _root: None)
    monkeypatch.setattr(
        release_validation,
        "validate_manifest",
        lambda _root: {"manifest_id": "test-manifest"},
    )
    monkeypatch.setattr(
        release_validation,
        "validate_documentation",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        release_validation,
        "validate_history_policy",
        lambda *_args, **_kwargs: None,
    )

    def reject_candidate_metadata(
        root: Path,
        *,
        schema_root: Path,
    ) -> dict[str, object]:
        nonlocal observed_root
        observed_root = root
        assert root != tmp_path
        assert (root / "candidate.txt").read_text(encoding="utf-8") == "candidate A\n"
        assert schema_root == tmp_path
        raise MetadataValidationError("candidate metadata sentinel")

    monkeypatch.setattr(
        release_validation,
        "validate_metadata_contracts",
        reject_candidate_metadata,
    )

    with pytest.raises(MetadataValidationError, match="candidate metadata sentinel"):
        validate_release_candidate(
            Path("governance-contract.json"),
            mode="prepare",
            candidate_ref=candidate_a,
            repository=tmp_path,
        )

    assert observed_root is not None
    assert not observed_root.exists()


def test_release_cli_reports_metadata_validation_failure_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        release_validation,
        "parse_args",
        lambda: SimpleNamespace(
            release=True,
            data_only=False,
            contract=Path("governance-contract.json"),
            mode="prepare",
            ref="candidate",
        ),
    )

    def reject_candidate(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise MetadataValidationError("candidate metadata sentinel")

    monkeypatch.setattr(release_validation, "validate_release_candidate", reject_candidate)

    assert release_validation.main() == 1
    captured = capsys.readouterr()
    assert "Release validation failed: candidate metadata sentinel" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    "mutation",
    ["default_branch", "release_tag", "unexpected_ref"],
)
def test_release_candidate_rechecks_contracted_refs_after_filesystem_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "release@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "candidate.txt").write_text("candidate\n", encoding="utf-8")
    subprocess.run(["git", "add", "candidate.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "Candidate"], cwd=tmp_path, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=tmp_path, check=True)
    contract = _future_contract(tmp_path)
    candidate_commit = str(contract["audited_commit"])
    alternate_commit = subprocess.run(
        [
            "git",
            "commit-tree",
            str(contract["audited_tree"]),
            "-p",
            candidate_commit,
            "-m",
            "Moved default ref",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    observed_root: Path | None = None

    def validate_initial_contract(
        _path: Path,
        repository: Path,
        **kwargs: object,
    ) -> dict[str, object]:
        release_validation.validate_history_policy(
            contract,
            repository,
            context=kwargs["context"],
            candidate_ref=kwargs["candidate_ref"],
        )
        return contract

    def late_mutation(_mode: str, _contract: object, root: Path) -> None:
        nonlocal observed_root
        observed_root = root
        if mutation == "default_branch":
            subprocess.run(
                ["git", "update-ref", "refs/heads/main", alternate_commit],
                cwd=tmp_path,
                check=True,
            )
        elif mutation == "release_tag":
            subprocess.run(
                ["git", "tag", "-a", "v2.0.0", "-m", "Future reproducibility release"],
                cwd=tmp_path,
                check=True,
            )
        else:
            subprocess.run(
                ["git", "update-ref", "refs/heads/unexpected", candidate_commit],
                cwd=tmp_path,
                check=True,
            )

    monkeypatch.setattr(
        release_validation,
        "validate_release_contract",
        validate_initial_contract,
    )
    monkeypatch.setattr(
        release_validation,
        "validate_tracked_file_types",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        release_validation,
        "validate_required_paths",
        lambda _contract, _root: None,
    )
    monkeypatch.setattr(
        release_validation,
        "validate_candidate_checksums",
        lambda _root, **_kwargs: 1,
    )
    monkeypatch.setattr(
        release_validation,
        "validate_data",
        lambda _root: {"dataset": {"rows": 1}},
    )
    monkeypatch.setattr(
        release_validation,
        "validate_metadata_contracts",
        lambda *_args, **_kwargs: {"data_sources": 31},
    )
    monkeypatch.setattr(release_validation, "validate_notebooks", lambda _root: None)
    monkeypatch.setattr(
        release_validation,
        "validate_manifest",
        lambda _root: {"manifest_id": "test-manifest"},
    )
    monkeypatch.setattr(release_validation, "validate_documentation", late_mutation)

    with pytest.raises(ContractValidationError):
        validate_release_candidate(
            Path("governance-contract.json"),
            mode="prepare",
            candidate_ref=candidate_commit,
            repository=tmp_path,
        )

    assert observed_root is not None
    assert not observed_root.exists()


@pytest.mark.parametrize("fail_inside", [False, True])
def test_materialized_candidate_cleans_up_after_success_and_failure(
    tmp_path: Path,
    fail_inside: bool,
) -> None:
    candidate_a, _governance_b = _initialize_candidate_repository(tmp_path)
    candidate_root: Path | None = None

    if fail_inside:
        with (
            pytest.raises(RuntimeError, match="synthetic validation failure"),
            materialized_candidate(tmp_path, candidate_a) as snapshot,
        ):
            candidate_root = snapshot.root
            raise RuntimeError("synthetic validation failure")
    else:
        with materialized_candidate(tmp_path, candidate_a) as snapshot:
            candidate_root = snapshot.root
            assert candidate_root.is_dir()

    assert candidate_root is not None
    assert not candidate_root.exists()
    worktrees = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert str(candidate_root) not in worktrees


def test_materialized_candidate_cleans_up_a_partially_failed_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_a, _governance_b = _initialize_candidate_repository(tmp_path)
    candidate_root: Path | None = None

    def fail_after_partial_write(
        _repository: Path,
        _tree: str,
        destination: Path,
    ) -> None:
        nonlocal candidate_root
        candidate_root = destination
        destination.mkdir()
        (destination / "partial.txt").write_text("partial\n", encoding="utf-8")
        raise ReleaseValidationError("synthetic materialization failure")

    monkeypatch.setattr(
        release_validation,
        "_materialize_candidate_tree",
        fail_after_partial_write,
    )
    with (
        pytest.raises(ReleaseValidationError, match="synthetic materialization failure"),
        materialized_candidate(tmp_path, candidate_a),
    ):
        pytest.fail("failed candidate materialization must not yield a snapshot")

    assert candidate_root is not None
    assert not candidate_root.exists()


def test_materialized_candidate_rejects_a_ref_that_moves_during_validation(tmp_path: Path) -> None:
    candidate_a, governance_b = _initialize_candidate_repository(tmp_path)
    subprocess.run(["git", "update-ref", "refs/heads/candidate", candidate_a], cwd=tmp_path, check=True)
    candidate_root: Path | None = None

    with (
        pytest.raises(ReleaseValidationError, match="Candidate ref moved during validation"),
        materialized_candidate(tmp_path, "refs/heads/candidate") as snapshot,
    ):
        candidate_root = snapshot.root
        subprocess.run(
            ["git", "update-ref", "refs/heads/candidate", governance_b],
            cwd=tmp_path,
            check=True,
        )

    assert candidate_root is not None
    assert not candidate_root.exists()


@pytest.mark.parametrize("configuration", ["local", "global"])
def test_materialized_candidate_disables_post_checkout_hooks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    configuration: str,
) -> None:
    candidate_a, _governance_b = _initialize_candidate_repository(tmp_path)
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    sentinel = tmp_path / "post-checkout-ran"
    hook = hooks / "post-checkout"
    hook.write_text(
        "#!/bin/sh\n"
        'printf "hook ran\\n" > "$RELEASE_HOOK_SENTINEL"\n',
        encoding="utf-8",
    )
    hook.chmod(0o755)
    monkeypatch.setenv("RELEASE_HOOK_SENTINEL", str(sentinel))
    if configuration == "local":
        subprocess.run(
            ["git", "config", "core.hooksPath", str(hooks)],
            cwd=tmp_path,
            check=True,
        )
    else:
        global_config = tmp_path / "global.gitconfig"
        global_config.write_text(
            f"[core]\n\thooksPath = {hooks}\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))

    with materialized_candidate(tmp_path, candidate_a) as snapshot:
        assert (snapshot.root / "candidate.txt").read_text(encoding="utf-8") == "candidate A\n"

    assert not sentinel.exists()


@pytest.mark.parametrize("configuration", ["local", "global"])
def test_materialized_candidate_does_not_execute_checkout_filters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    configuration: str,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "release@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "candidate.txt").write_text("candidate A\n", encoding="utf-8")
    (tmp_path / ".gitattributes").write_text(
        "candidate.txt filter=sentinel\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "candidate.txt", ".gitattributes"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "Candidate A with filter"], cwd=tmp_path, check=True)
    candidate_a = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (tmp_path / "candidate.txt").write_text("governance B\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "Governance B"], cwd=tmp_path, check=True)

    sentinel = tmp_path / "checkout-filter-ran"
    filter_script = tmp_path / "checkout-filter.sh"
    filter_script.write_text(
        "#!/bin/sh\n"
        'printf "filter ran\\n" > "$RELEASE_FILTER_SENTINEL"\n'
        "cat\n",
        encoding="utf-8",
    )
    filter_script.chmod(0o755)
    monkeypatch.setenv("RELEASE_FILTER_SENTINEL", str(sentinel))
    monkeypatch.setenv("RELEASE_FILTER_SCRIPT", str(filter_script))
    config_command = ["git", "config"]
    if configuration == "global":
        global_config = tmp_path / "global.gitconfig"
        global_config.write_text("", encoding="utf-8")
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
        config_command.extend(["--file", str(global_config)])
    subprocess.run(
        [*config_command, "filter.sentinel.smudge", 'sh "$RELEASE_FILTER_SCRIPT"'],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        [*config_command, "filter.sentinel.clean", "cat"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        [*config_command, "filter.sentinel.required", "true"],
        cwd=tmp_path,
        check=True,
    )

    with materialized_candidate(tmp_path, candidate_a) as snapshot:
        assert (snapshot.root / "candidate.txt").read_bytes() == b"candidate A\n"

    assert not sentinel.exists()


def test_materialized_candidate_preserves_executable_mode(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "release@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    executable = tmp_path / "tool.sh"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    subprocess.run(["git", "add", "tool.sh"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "Executable candidate"], cwd=tmp_path, check=True)
    candidate = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    with materialized_candidate(tmp_path, candidate) as snapshot:
        assert snapshot.root.joinpath("tool.sh").stat().st_mode & 0o777 == 0o755


def test_materialized_candidate_ignores_git_replace_objects(tmp_path: Path) -> None:
    candidate_a, _governance_b = _initialize_candidate_repository(tmp_path)
    candidate_blob = subprocess.run(
        ["git", "rev-parse", f"{candidate_a}:candidate.txt"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    replacement_blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        input=b"replacement bytes\n",
    ).stdout.decode("ascii").strip()
    subprocess.run(
        ["git", "replace", candidate_blob, replacement_blob],
        cwd=tmp_path,
        check=True,
    )

    with materialized_candidate(tmp_path, candidate_a) as snapshot:
        assert (snapshot.root / "candidate.txt").read_bytes() == b"candidate A\n"


@pytest.mark.parametrize("candidate_ref", ["", " HEAD", "--help", "HEAD\nrefs/heads/main"])
def test_materialized_candidate_rejects_unsafe_ref_arguments(
    tmp_path: Path,
    candidate_ref: str,
) -> None:
    _initialize_candidate_repository(tmp_path)

    with (
        pytest.raises(ReleaseValidationError, match="Candidate ref"),
        materialized_candidate(tmp_path, candidate_ref),
    ):
        pytest.fail("unsafe candidate ref must not be materialized")


def test_git_object_access_is_exact_and_disables_lazy_fetch() -> None:
    environment = no_lazy_fetch_environment()

    assert environment["GIT_NO_LAZY_FETCH"] == "1"
    assert environment["GIT_NO_REPLACE_OBJECTS"] == "1"


@pytest.mark.parametrize("truthy", ["true", "yes", "on", "1"])
def test_materialized_candidate_rejects_promisor_repository(
    tmp_path: Path,
    truthy: str,
) -> None:
    candidate_a, _governance_b = _initialize_candidate_repository(tmp_path)
    subprocess.run(
        ["git", "config", "remote.origin.promisor", truthy],
        cwd=tmp_path,
        check=True,
    )

    with (
        pytest.raises(ReleaseValidationError, match="promisor remotes are not supported"),
        materialized_candidate(tmp_path, candidate_a),
    ):
        pytest.fail("promisor repository must not materialize a candidate")


def test_release_validation_rejects_tracked_symlink(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    outside = tmp_path.parent / "outside-release-file.txt"
    outside.write_text("not public\n", encoding="utf-8")
    (tmp_path / "linked.txt").symlink_to(outside)
    subprocess.run(["git", "add", "linked.txt"], cwd=tmp_path, check=True)

    with pytest.raises(ReleaseValidationError, match="not a regular file"):
        validate_tracked_file_types(tmp_path)


def test_release_validation_uses_only_contracted_required_paths(tmp_path: Path) -> None:
    contracted = tmp_path / "historical.txt"
    contracted.write_text("present in historical candidate\n", encoding="utf-8")

    validate_required_paths({"required_paths": ["historical.txt"]}, tmp_path)

    with pytest.raises(ReleaseValidationError, match="historical.txt"):
        validate_required_paths({"required_paths": ["historical.txt"]}, tmp_path / "missing")


def test_v1_candidate_uses_v1_contract_paths_and_checksum_inventory() -> None:
    contract = json.loads(
        (ROOT / "release/contracts/v1.0.0.json").read_text(encoding="utf-8")
    )

    with materialized_candidate(ROOT, "v1.0.0") as candidate:
        assert not (candidate.root / "AGENTS.md").exists()
        validate_required_paths(contract, candidate.root)
        assert (
            validate_candidate_checksums(
                candidate.root,
                repository=ROOT,
                tree=candidate.tree,
            )
            > 0
        )


def test_candidate_checksum_validation_reads_materialized_tree(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    candidate = tmp_path / "candidate.txt"
    candidate.write_text("candidate bytes\n", encoding="utf-8")
    checksum_dir = tmp_path / "checksums"
    checksum_dir.mkdir()
    checksum = hashlib.sha256(candidate.read_bytes()).hexdigest()
    manifest = checksum_dir / "SHA256SUMS"
    manifest.write_text(f"{checksum}  candidate.txt\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)

    assert validate_candidate_checksums(tmp_path) == 1

    candidate.write_text("governance bytes\n", encoding="utf-8")
    with pytest.raises(ReleaseValidationError, match="mismatch: candidate.txt"):
        validate_candidate_checksums(tmp_path)


def test_smoke_and_audit_make_targets_are_offline() -> None:
    smoke = subprocess.run(
        ["make", "-n", "smoke"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    audit = subprocess.run(
        ["make", "-n", "audit"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert "uv lock --check" in smoke
    assert "scripts/verify_checksums.py" in smoke
    assert "scripts/validate_contracts.py" in smoke
    assert "scripts/validate_release.py --data-only" in smoke
    assert "scripts/reproduce_paper.py --offline" in audit
    assert "git diff --check" in audit
    assert "git diff --cached --check" in audit
    for forbidden in ("scripts/run_replication.py", "--confirm-live-api", "release-check", "curl ", "wget "):
        assert forbidden not in smoke
        assert forbidden not in audit
    for command in (*smoke.splitlines(), *audit.splitlines()):
        if "uv run" in command:
            assert "--offline" in command
            assert "--no-sync" in command


def test_release_make_targets_propagate_contract_and_ref() -> None:
    output = subprocess.run(
        [
            "make",
            "-n",
            "release-archive",
            "RELEASE_CONTRACT=release/contracts/future.json",
            "RELEASE_REF=v2.0.0",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "--contract release/contracts/future.json" in output
    assert "--ref v2.0.0" in output
    assert "--candidate-contract release/contracts/future.json" in output
