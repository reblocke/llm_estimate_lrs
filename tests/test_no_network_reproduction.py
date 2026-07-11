from __future__ import annotations

import json
import shutil
import socket
from pathlib import Path

import pytest

from scripts import reproduce_paper

ROOT = Path(__file__).resolve().parents[1]


def test_offline_reproduction_needs_no_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    output = tmp_path / "reproduction"
    paths = reproduce_paper.reproduce_paper(
        output,
        offline=True,
        repository_root=ROOT,
    )

    summary = json.loads(paths["run_summary"].read_text(encoding="utf-8"))
    report = json.loads(paths["validation_report"].read_text(encoding="utf-8"))
    assert summary["status"] == "passed"
    assert summary["network_blocked"] is True
    assert summary["api_key_required"] is False
    assert summary["notebooks_executed"] is False
    assert summary["live_requests_made"] is False
    assert report["status"] == "passed"
    assert report["comparison_count"] == len(list((ROOT / "results/reference").iterdir()))
    assert all(artifact["status"] == "match" for artifact in report["artifacts"])

    tracked_names = sorted(path.name for path in (ROOT / "results/reference").iterdir() if path.is_file())
    generated_names = sorted(path.name for path in paths["generated_reference"].iterdir() if path.is_file())
    assert generated_names == tracked_names


def test_reproduction_actively_blocks_socket_creation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_socket = socket.socket

    def network_attempt(_input: Path, _output: Path) -> dict[str, Path]:
        socket.socket()
        raise AssertionError("socket construction unexpectedly succeeded")

    monkeypatch.setattr(reproduce_paper, "compute_reference_results", network_attempt)
    with pytest.raises(reproduce_paper.OfflineNetworkError, match="Network access is blocked"):
        reproduce_paper.reproduce_paper(
            tmp_path / "blocked",
            offline=True,
            repository_root=ROOT,
        )
    assert socket.socket is original_socket


def test_reproduction_refuses_overwrite_without_explicit_replace(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    canonical_parent = repository / reproduce_paper.CANONICAL_RELATIVE_PATH.parent
    canonical_parent.mkdir(parents=True)
    shutil.copy2(ROOT / reproduce_paper.CANONICAL_RELATIVE_PATH, canonical_parent)
    shutil.copytree(
        ROOT / reproduce_paper.REFERENCE_RELATIVE_PATH,
        repository / reproduce_paper.REFERENCE_RELATIVE_PATH,
    )
    output = repository / "results/runs/reproduction"
    output.mkdir(parents=True)
    sentinel = output / "sentinel.txt"
    sentinel.write_text("old\n", encoding="utf-8")

    with pytest.raises(reproduce_paper.ReproductionError, match="already exists"):
        reproduce_paper.reproduce_paper(output, offline=True, repository_root=repository)
    assert sentinel.exists()

    reproduce_paper.reproduce_paper(
        output,
        offline=True,
        replace_output=True,
        repository_root=repository,
    )
    assert not sentinel.exists()
    assert (output / "run_summary.json").is_file()


def test_reproduction_requires_offline_and_protects_release_paths(tmp_path: Path) -> None:
    with pytest.raises(reproduce_paper.ReproductionError, match="requires --offline"):
        reproduce_paper.reproduce_paper(
            tmp_path / "not-offline",
            offline=False,
            repository_root=ROOT,
        )


def test_replace_is_restricted_and_symlink_is_never_followed(tmp_path: Path) -> None:
    arbitrary = tmp_path / "arbitrary"
    arbitrary.mkdir()
    arbitrary_sentinel = arbitrary / "sentinel.txt"
    arbitrary_sentinel.write_text("keep\n", encoding="utf-8")
    with pytest.raises(reproduce_paper.ReproductionError, match="restricted"):
        reproduce_paper.reproduce_paper(
            arbitrary,
            offline=True,
            replace_output=True,
            repository_root=ROOT,
        )
    assert arbitrary_sentinel.read_text(encoding="utf-8") == "keep\n"

    target = tmp_path / "target"
    target.mkdir()
    target_sentinel = target / "sentinel.txt"
    target_sentinel.write_text("keep\n", encoding="utf-8")
    output_link = tmp_path / "output-link"
    output_link.symlink_to(target, target_is_directory=True)
    with pytest.raises(reproduce_paper.ReproductionError, match="symbolic link"):
        reproduce_paper.reproduce_paper(
            output_link,
            offline=True,
            replace_output=True,
            repository_root=ROOT,
        )
    assert target_sentinel.read_text(encoding="utf-8") == "keep\n"
    with pytest.raises(reproduce_paper.ReproductionError, match="frozen release path"):
        reproduce_paper.reproduce_paper(
            ROOT / "results/reference",
            offline=True,
            replace_output=True,
            repository_root=ROOT,
        )


def test_replace_rejects_symlinked_output_ancestor(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    runs_parent = repository / "results"
    runs_parent.mkdir(parents=True)
    external_runs = tmp_path / "external-runs"
    external_output = external_runs / "reproduction"
    external_output.mkdir(parents=True)
    sentinel = external_output / "sentinel.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    (runs_parent / "runs").symlink_to(external_runs, target_is_directory=True)

    output = repository / "results/runs/reproduction"
    with pytest.raises(reproduce_paper.ReproductionError, match="contains a symbolic link"):
        reproduce_paper._validate_output_path(
            output,
            repository,
            replace_output=True,
        )
    assert sentinel.read_text(encoding="utf-8") == "keep\n"


def test_offline_entrypoint_has_no_live_or_notebook_dependencies() -> None:
    source = (ROOT / "scripts/reproduce_paper.py").read_text(encoding="utf-8")
    for forbidden in ("OpenAI(", "papermill", "nbclient", "requests.get", "urlopen("):
        assert forbidden not in source
