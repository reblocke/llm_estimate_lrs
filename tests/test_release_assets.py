from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import nbformat
import pytest

from scripts import build_release_assets
from scripts.build_release_assets import (
    VERIFICATION_INPUTS,
    ReleaseAssetError,
    _network_guard_source,
    _scrub_execution_metadata,
    _validation_report,
    execute_verification_notebooks,
    expected_asset_paths,
    materialize_reviewed_inputs,
    require_clean_ref,
    verify_release_asset_determinism,
    write_asset_checksums,
)
from scripts.generate_release_attestation import generate_attestation

ROOT = Path(__file__).resolve().parents[1]


def _contract(commit: str, version: str = "1.1.0") -> dict[str, object]:
    return {
        "release_version": version,
        "release_ref": f"v{version}",
        "release_date": "2026-07-27",
        "audited_commit": commit,
        "article": {
            "doi": "10.1038/s41598-026-61766-2",
            "published_date": "2026-07-11",
        },
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_reference_archive_is_deterministic_and_contains_no_figures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    members = tuple(path for path in build_release_assets.REFERENCE_MEMBERS if path != "checksums/SHA256SUMS")
    monkeypatch.setattr(build_release_assets, "REFERENCE_MEMBERS", members)
    first = build_release_assets.build_reference_archive(ROOT, tmp_path / "first.zip")
    second = build_release_assets.build_reference_archive(ROOT, tmp_path / "second.zip")
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == list(members)
        assert all(member.compress_type == zipfile.ZIP_STORED for member in archive.infolist())
        assert not any(name.lower().endswith((".pdf", ".png", ".tif", ".tiff")) for name in archive.namelist())


def test_reference_archive_reads_head_blob_not_working_tree_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "release@example.invalid"], cwd=repository, check=True)
    source = repository / "reference.csv"
    source.write_text("reviewed,value\n", encoding="utf-8")
    subprocess.run(["git", "add", "reference.csv"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "Add reference source"], cwd=repository, check=True)

    outside = tmp_path / "private.csv"
    outside.write_text("private,value\n", encoding="utf-8")
    source.unlink()
    source.symlink_to(outside)
    monkeypatch.setattr(build_release_assets, "REFERENCE_MEMBERS", ("reference.csv",))

    archive_path = build_release_assets.build_reference_archive(repository, tmp_path / "reference.zip")
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.read("reference.csv") == b"reviewed,value\n"


def test_reference_archive_ignores_broken_legacy_temp_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "release@example.invalid"], cwd=repository, check=True)
    (repository / "reference.csv").write_text("reviewed,value\n", encoding="utf-8")
    subprocess.run(["git", "add", "reference.csv"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "Add reference source"], cwd=repository, check=True)
    monkeypatch.setattr(build_release_assets, "REFERENCE_MEMBERS", ("reference.csv",))

    output = tmp_path / "reference.zip"
    outside_output = tmp_path / "outside-reference.zip"
    output.symlink_to(outside_output)
    legacy_temp = output.with_suffix(output.suffix + ".tmp")
    outside_temp = tmp_path / "outside-reference-temp.zip"
    legacy_temp.symlink_to(outside_temp)

    archive_path = build_release_assets.build_reference_archive(repository, output)

    assert archive_path == output
    assert output.is_file() and not output.is_symlink()
    assert legacy_temp.is_symlink()
    assert not outside_output.exists()
    assert not outside_temp.exists()


def test_verification_inputs_are_materialized_from_pinned_git_blobs(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "release@example.invalid"], cwd=repository, check=True)
    committed = {relative: f"reviewed:{relative}\n".encode() for relative in VERIFICATION_INPUTS}
    for relative, payload in committed.items():
        (repository / relative).write_bytes(payload)
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "Add verification inputs"], cwd=repository, check=True)
    pinned_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    (repository / VERIFICATION_INPUTS[0]).write_bytes(b"changed working-tree bytes\n")
    outside = tmp_path / "outside-input"
    outside.write_bytes(b"outside bytes\n")
    swapped = repository / VERIFICATION_INPUTS[1]
    swapped.unlink()
    swapped.symlink_to(outside)

    destination = tmp_path / "staged"
    hashes = materialize_reviewed_inputs(repository, pinned_commit, VERIFICATION_INPUTS, destination)

    assert set(hashes) == set(VERIFICATION_INPUTS)
    for relative, payload in committed.items():
        assert (destination / relative).read_bytes() == payload
        assert hashes[relative] == hashlib.sha256(payload).hexdigest()


def test_verification_notebook_output_directory_symlink_cannot_delete_outside_files(tmp_path: Path) -> None:
    outside = tmp_path / "outside-notebooks"
    outside.mkdir()
    sentinel = outside / "sentinel.ipynb"
    sentinel.write_bytes(b"outside notebook bytes\n")
    output_dir = tmp_path / "notebooks"
    output_dir.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ReleaseAssetError, match="symbolic link"):
        execute_verification_notebooks(ROOT, output_dir, "HEAD")
    assert output_dir.is_symlink()
    assert sentinel.read_bytes() == b"outside notebook bytes\n"


def test_validation_report_uses_governance_validator_not_candidate_tooling(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "release@example.invalid"], cwd=repository, check=True)
    validator = repository / "scripts" / "validate_release.py"
    validator.parent.mkdir()
    candidate_marker = tmp_path / "candidate-validator-ran"
    validator.write_text(
        "import json\n"
        "from pathlib import Path\n"
        f"Path({str(candidate_marker)!r}).write_text('ran')\n"
        "print(json.dumps({'source': 'candidate'}))\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "Add candidate validator"], cwd=repository, check=True)
    pinned_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    validator.write_text(
        "import json\n"
        "import sys\n"
        "print(json.dumps({'source': 'governance', 'arguments': sys.argv[1:]}))\n",
        encoding="utf-8",
    )
    contract = repository / "release" / "contracts" / "future.json"
    contract.parent.mkdir(parents=True)
    contract.write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "Add governance validator and contract"], cwd=repository, check=True)
    governance_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    outside_report = tmp_path / "outside-validation-report.json"
    outside_report.write_text("keep\n", encoding="utf-8")
    requested_output = tmp_path / "validation-report.json"
    requested_output.symlink_to(outside_report)
    output = _validation_report(
        repository,
        pinned_commit,
        "prepare",
        requested_output,
        contract=Path("release/contracts/future.json"),
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["source"] == "governance"
    assert report["arguments"][-2:] == ["--ref", pinned_commit]
    assert output.is_file() and not output.is_symlink()
    assert outside_report.read_text(encoding="utf-8") == "keep\n"
    assert not candidate_marker.exists()
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == governance_head
    )
    worktrees = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert worktrees.count("worktree ") == 1


def test_clean_governance_checkout_may_validate_an_earlier_candidate(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "release@example.invalid"], cwd=repository, check=True)
    (repository / "candidate.txt").write_text("candidate\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "Candidate"], cwd=repository, check=True)
    candidate = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (repository / "governance.txt").write_text("contract and validator\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "Governance record"], cwd=repository, check=True)

    assert require_clean_ref(repository, candidate) == candidate


def test_asset_build_requires_complete_local_candidate_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    pinned_commit = "a" * 40
    monkeypatch.setattr(
        build_release_assets,
        "load_contract",
        lambda _contract_path, _repository: _contract(pinned_commit),
    )
    monkeypatch.setattr(
        build_release_assets,
        "require_clean_ref",
        lambda _repository, _ref: pinned_commit,
    )
    monkeypatch.setattr(
        build_release_assets,
        "require_full_local_clone",
        lambda _repository: None,
    )

    def reject_partial_clone(candidate_repository: Path, revision: str) -> None:
        assert candidate_repository == repository.resolve()
        assert revision == pinned_commit
        raise ValueError("partial clones are not supported")

    monkeypatch.setattr(
        build_release_assets,
        "require_complete_local_objects",
        reject_partial_clone,
    )
    monkeypatch.setattr(
        build_release_assets,
        "build_archive",
        lambda *_args, **_kwargs: pytest.fail("asset construction must not start"),
    )

    with pytest.raises(ValueError, match="partial clones are not supported"):
        build_release_assets.build_release_assets(
            repository,
            repository / "dist",
            "HEAD",
            "prepare",
            contract=Path("release/contracts/future.json"),
        )

    assert not (repository / "dist").exists()


def test_failed_candidate_validation_prevents_notebook_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    marker = tmp_path / "notebook-executed"
    pinned_commit = "a" * 40
    monkeypatch.setattr(
        build_release_assets,
        "load_contract",
        lambda _contract_path, _repository: _contract(pinned_commit),
    )
    monkeypatch.setattr(build_release_assets, "require_full_local_clone", lambda _root: None)
    monkeypatch.setattr(
        build_release_assets,
        "require_clean_ref",
        lambda _root, _ref: pinned_commit,
    )
    monkeypatch.setattr(
        build_release_assets,
        "require_complete_local_objects",
        lambda _root, _revision: None,
    )
    monkeypatch.setattr(
        build_release_assets,
        "build_archive",
        lambda _root, output, _ref: output,
    )
    monkeypatch.setattr(
        build_release_assets,
        "build_reference_archive",
        lambda _root, output, _ref: output,
    )

    def execute_candidate(*_args: object, **_kwargs: object) -> list[Path]:
        marker.write_text("executed\n", encoding="utf-8")
        return []

    monkeypatch.setattr(
        build_release_assets,
        "execute_verification_notebooks",
        execute_candidate,
    )
    monkeypatch.setattr(
        build_release_assets,
        "_validation_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ReleaseAssetError("candidate contract validation failed")
        ),
    )

    with pytest.raises(ReleaseAssetError, match="contract validation failed"):
        build_release_assets.build_release_assets(
            repository,
            repository / "dist",
            "candidate",
            "prepare",
            contract=Path("release/contracts/future.json"),
        )

    assert not marker.exists()


def test_ref_movement_after_validation_prevents_notebook_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    marker = tmp_path / "notebook-executed"
    pinned_commit = "a" * 40
    moved_commit = "b" * 40
    monkeypatch.setattr(
        build_release_assets,
        "load_contract",
        lambda _contract_path, _repository: _contract(pinned_commit),
    )
    resolved = iter((pinned_commit, moved_commit))
    monkeypatch.setattr(build_release_assets, "require_full_local_clone", lambda _root: None)
    monkeypatch.setattr(
        build_release_assets,
        "require_clean_ref",
        lambda _root, _ref: next(resolved),
    )
    monkeypatch.setattr(
        build_release_assets,
        "require_complete_local_objects",
        lambda _root, _revision: None,
    )
    monkeypatch.setattr(
        build_release_assets,
        "build_archive",
        lambda _root, output, _ref: output,
    )
    monkeypatch.setattr(
        build_release_assets,
        "build_reference_archive",
        lambda _root, output, _ref: output,
    )

    def write_report(
        _root: Path,
        _commit: str,
        _mode: str,
        output: Path,
        *,
        contract: Path | None = None,
    ) -> Path:
        assert contract is not None
        output.write_text("{}\n", encoding="utf-8")
        return output

    def execute_candidate(*_args: object, **_kwargs: object) -> list[Path]:
        marker.write_text("executed\n", encoding="utf-8")
        return []

    monkeypatch.setattr(build_release_assets, "_validation_report", write_report)
    monkeypatch.setattr(
        build_release_assets,
        "execute_verification_notebooks",
        execute_candidate,
    )

    with pytest.raises(ReleaseAssetError, match="changed during candidate validation"):
        build_release_assets.build_release_assets(
            repository,
            repository / "dist",
            "candidate",
            "prepare",
            contract=Path("release/contracts/future.json"),
        )

    assert not marker.exists()


def test_validation_report_propagates_contract_and_pinned_candidate_commit(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "release@example.invalid"], cwd=repository, check=True)
    validator = repository / "scripts" / "validate_release.py"
    validator.parent.mkdir()
    validator.write_text(
        "import json\nimport sys\nprint(json.dumps({'arguments': sys.argv[1:]}))\n",
        encoding="utf-8",
    )
    contract = repository / "release" / "contracts" / "future.json"
    contract.parent.mkdir(parents=True)
    contract.write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "Add release validator"], cwd=repository, check=True)
    pinned_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    output = _validation_report(
        repository,
        pinned_commit,
        "final",
        tmp_path / "validation-report.json",
        contract=Path("release/contracts/future.json"),
    )

    assert json.loads(output.read_text(encoding="utf-8"))["arguments"] == [
        "--release",
        "--mode",
        "final",
        "--contract",
        "release/contracts/future.json",
        "--ref",
        pinned_commit,
    ]


def _fake_asset_builder(tmp_path: Path, *, divergence: str | None = None):
    calls: list[int] = []
    expected_paths = expected_asset_paths("1.1.0")

    def builder(
        _repository: Path,
        output_dir: Path,
        _ref: str,
        _mode: str,
        *,
        contract: Path | None = None,
    ) -> dict[str, Path]:
        assert contract == Path("release/contracts/future.json")
        calls.append(len(calls) + 1)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        for relative in expected_paths:
            path = output_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"stable:{relative}\n", encoding="utf-8")
        if len(calls) == 2 and divergence == "changed":
            (output_dir / "validation-report.json").write_text("changed\n", encoding="utf-8")
        elif len(calls) == 2 and divergence == "missing":
            (output_dir / "validation-report.json").unlink()
        elif len(calls) == 2 and divergence == "extra":
            (output_dir / "extra.txt").write_text("extra\n", encoding="utf-8")
        return {"asset_checksums": output_dir / "SHA256SUMS"}

    return calls, builder


def test_two_build_full_asset_determinism_accepts_identical_inventories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, builder = _fake_asset_builder(tmp_path)
    monkeypatch.setattr(build_release_assets, "build_release_assets", builder)
    monkeypatch.setattr(
        build_release_assets,
        "load_contract",
        lambda _contract_path, _repository: _contract("a" * 40),
    )
    output_dir = tmp_path / "dist"

    assets = verify_release_asset_determinism(
        tmp_path,
        output_dir,
        "HEAD",
        "prepare",
        contract=Path("release/contracts/future.json"),
    )

    assert calls == [1, 2]
    assert assets == {"asset_checksums": output_dir / "SHA256SUMS"}
    assert set(build_release_assets.asset_inventory(output_dir)) == expected_asset_paths("1.1.0")


@pytest.mark.parametrize("divergence", ["changed", "missing", "extra"])
def test_two_build_full_asset_determinism_rejects_inventory_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, divergence: str
) -> None:
    calls, builder = _fake_asset_builder(tmp_path, divergence=divergence)
    monkeypatch.setattr(build_release_assets, "build_release_assets", builder)
    monkeypatch.setattr(
        build_release_assets,
        "load_contract",
        lambda _contract_path, _repository: _contract("a" * 40),
    )

    with pytest.raises(ReleaseAssetError):
        verify_release_asset_determinism(
            tmp_path,
            tmp_path / "dist",
            "HEAD",
            "prepare",
            contract=Path("release/contracts/future.json"),
        )
    assert calls == [1, 2]


def test_expected_asset_paths_are_derived_from_contract_version() -> None:
    assert expected_asset_paths("1.0.0") == {
        "SHA256SUMS",
        "llm-estimate-lrs-v1.0.0.zip",
        "notebooks/data_analysis.executed.ipynb",
        "notebooks/supplementary_analyses.executed.ipynb",
        "reference-tables-v1.0.0.zip",
        "release-attestation.json",
        "validation-report.json",
    }
    assert {
        "llm-estimate-lrs-v1.1.0.zip",
        "reference-tables-v1.1.0.zip",
    } <= expected_asset_paths("1.1.0")


@pytest.mark.parametrize(
    "script_name",
    ["build_release_assets.py", "generate_release_attestation.py"],
)
def test_release_asset_clis_require_explicit_ref(
    tmp_path: Path,
    script_name: str,
) -> None:
    script = ROOT / "scripts" / script_name
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--contract",
            "release/contracts/v1.0.0.json",
            "--output",
            str(tmp_path / "output.json"),
        ]
        if script_name == "generate_release_attestation.py"
        else [
            sys.executable,
            str(script),
            "--contract",
            "release/contracts/v1.0.0.json",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "--ref" in result.stderr


def test_asset_checksum_inventory_covers_attestation_but_not_itself(tmp_path: Path) -> None:
    (tmp_path / "source.zip").write_bytes(b"source")
    (tmp_path / "release-attestation.json").write_text("{}\n", encoding="utf-8")
    output = write_asset_checksums(tmp_path, tmp_path / "SHA256SUMS")
    lines = output.read_text(encoding="utf-8").splitlines()
    assert [line.split("  ", 1)[1] for line in lines] == ["release-attestation.json", "source.zip"]
    assert lines[0].startswith(sha256(tmp_path / "release-attestation.json"))


def test_asset_checksum_output_symlink_is_rejected_without_touching_target(tmp_path: Path) -> None:
    (tmp_path / "source.zip").write_bytes(b"source")
    outside = tmp_path.parent / "outside-checksums.txt"
    outside.write_text("keep\n", encoding="utf-8")
    output = tmp_path / "SHA256SUMS"
    output.symlink_to(outside)

    with pytest.raises(ReleaseAssetError, match="cannot be a symbolic link"):
        write_asset_checksums(tmp_path, output)
    assert output.is_symlink()
    assert outside.read_text(encoding="utf-8") == "keep\n"


def test_executed_notebook_scrub_removes_dates_and_local_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    notebook_path = tmp_path / "executed.ipynb"
    notebook = nbformat.v4.new_notebook(
        cells=[
            nbformat.v4.new_code_cell(
                "print('output')",
                execution_count=1,
                outputs=[
                    nbformat.v4.new_output(
                        "stream",
                        name="stdout",
                        text=f"{workspace}/results/2026-07-10/table.csv\n",
                    ),
                    nbformat.v4.new_output(
                        "stream",
                        name="stderr",
                        text="irrelevant warning with a temporary path\n",
                    ),
                ],
            )
        ]
    )
    nbformat.write(notebook, notebook_path)
    _scrub_execution_metadata(notebook_path, workspace)
    scrubbed = notebook_path.read_text(encoding="utf-8")
    assert str(workspace) not in scrubbed
    assert "2026-07-10" not in scrubbed
    assert "verification-workspace/results/verification-run/table.csv" in scrubbed
    assert "irrelevant warning" not in scrubbed


def test_verification_kernel_suppresses_figure_file_writes(tmp_path: Path) -> None:
    guard = tmp_path / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(_network_guard_source(), encoding="utf-8")
    target = tmp_path / "figure.pdf"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(guard)
    subprocess.run(
        [
            sys.executable,
            "-c",
            f"import matplotlib.pyplot as plt; plt.plot([0, 1]); plt.savefig({str(target)!r})",
        ],
        env=environment,
        check=True,
    )
    assert not target.exists()


def test_attestation_resolves_requested_ref_and_hashes_assets(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "release@example.invalid"], cwd=repository, check=True)
    (repository / "manifests").mkdir()
    (repository / "checksums").mkdir()
    committed_manifest = b"{}\n"
    committed_checksums = ("0" * 64 + "  file\n").encode()
    (repository / "manifests/manuscript_run_v1.json").write_bytes(committed_manifest)
    (repository / "checksums/SHA256SUMS").write_bytes(committed_checksums)
    (repository / "file").write_text("value\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "Initial release tree"], cwd=repository, check=True)
    (repository / "manifests/manuscript_run_v1.json").write_text('{"changed":true}\n', encoding="utf-8")
    (repository / "checksums/SHA256SUMS").write_text("changed\n", encoding="utf-8")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assets = tmp_path / "assets"
    assets.mkdir()
    asset = assets / "source.zip"
    asset.write_bytes(b"source")
    output = generate_attestation(
        repository,
        "HEAD",
        [asset],
        assets / "attestation.json",
        contract=_contract(commit),
        asset_root=assets,
    )
    document = json.loads(output.read_text(encoding="utf-8"))
    assert (
        document["release_commit"]
        == subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True
        ).stdout.strip()
    )
    assert document["assets"] == [{"bytes": 6, "path": "source.zip", "sha256": sha256(asset)}]
    assert document["schema_version"] == 2
    assert document["release_version"] == "1.1.0"
    assert document["release_ref"] == "v1.1.0"
    assert document["release_date"] == "2026-07-27"
    assert document["requested_ref"] == "HEAD"
    assert document["article_doi"] == "10.1038/s41598-026-61766-2"
    assert document["manifest_sha256"] == hashlib.sha256(committed_manifest).hexdigest()
    assert document["repository_checksums_sha256"] == hashlib.sha256(committed_checksums).hexdigest()


def test_attestation_rejects_asset_symlink_and_atomically_replaces_output_symlink(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "release@example.invalid"], cwd=repository, check=True)
    (repository / "manifests").mkdir()
    (repository / "checksums").mkdir()
    (repository / "manifests/manuscript_run_v1.json").write_text("{}\n", encoding="utf-8")
    (repository / "checksums/SHA256SUMS").write_text("inventory\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "Initial release tree"], cwd=repository, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assets = tmp_path / "assets"
    assets.mkdir()
    outside_asset = tmp_path / "outside-asset.zip"
    outside_asset.write_bytes(b"outside asset bytes")
    linked_asset = assets / "source.zip"
    linked_asset.symlink_to(outside_asset)
    with pytest.raises(ValueError, match="symbolic link"):
        generate_attestation(
            repository,
            "HEAD",
            [linked_asset],
            assets / "attestation.json",
            contract=_contract(commit),
            asset_root=assets,
        )
    assert outside_asset.read_bytes() == b"outside asset bytes"

    linked_asset.unlink()
    linked_asset.write_bytes(b"reviewed source")
    outside_output = tmp_path / "outside-attestation.json"
    output = assets / "attestation.json"
    output.symlink_to(outside_output)
    generated = generate_attestation(
        repository,
        "HEAD",
        [linked_asset],
        output,
        contract=_contract(commit),
        asset_root=assets,
    )
    assert generated == output
    assert output.is_file() and not output.is_symlink()
    assert not outside_output.exists()
