from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

import dotenv
import pytest

from scripts import run_replication


@pytest.fixture(autouse=True)
def _fixed_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        run_replication,
        "_current_commit_sha",
        lambda _repository: "abcdef1" + ("0" * 33),
    )
    monkeypatch.setattr(run_replication, "_require_clean_worktree", lambda _repository: None)


def _write_csv(path: Path, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row_id"])
        writer.writerows([[f"row_{index:04d}"] for index in range(rows)])


def _release_fixture(root: Path) -> None:
    for experiment in run_replication.EXPERIMENTS.values():
        (root / str(experiment["notebook"])).write_text("{}\n", encoding="utf-8")
        (root / str(experiment["prompt"])).parent.mkdir(parents=True, exist_ok=True)
        (root / str(experiment["prompt"])).write_text("{}\n", encoding="utf-8")
        _write_csv(root / str(experiment["input"]), int(experiment["expected_rows"]))


def _args(root: Path, **overrides) -> argparse.Namespace:
    values = {
        "run_id": "2026-07-10_validation_abcdef1",
        "experiment": "main",
        "models": list(run_replication.MANUSCRIPT_MODELS),
        "max_calls": 2100,
        "confirm_live_api": "YES",
        "runs_root": root / "runs",
        "dry_run": True,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _with_staged_artifacts(plan: dict[str, object], root: Path) -> dict[str, object]:
    staged = dict(plan)
    stage_root = root / "staged"
    stage_root.mkdir(exist_ok=True)
    for artifact in ("notebook", "input", "prompt"):
        source = Path(plan[f"{artifact}_path"])
        destination = stage_root / source.name
        shutil.copyfile(source, destination)
        staged[f"staged_{artifact}_path"] = destination
        staged[f"{artifact}_sha256"] = run_replication.sha256_file(destination)
    staged["started_at_utc"] = "2026-07-11T00:00:00+00:00"
    return staged


def test_run_id_requires_date_description_and_short_sha() -> None:
    run_replication.validate_run_id("2026-07-10_validation_abcdef1")
    for invalid in (
        "validation",
        "2026-99-10_validation_abcdef1",
        "2026-07-10_Validation_abcdef1",
        "2026-07-10_validation_notasha",
        "../2026-07-10_validation_abcdef1",
    ):
        with pytest.raises(run_replication.ReplicationError):
            run_replication.validate_run_id(invalid)


def test_request_requires_exact_confirmation_before_artifact_checks(tmp_path: Path) -> None:
    _release_fixture(tmp_path)
    original_root = run_replication.REPOSITORY_ROOT
    run_replication.REPOSITORY_ROOT = tmp_path
    try:
        with pytest.raises(run_replication.ReplicationError, match="exactly YES"):
            run_replication.validate_request(_args(tmp_path, confirm_live_api="yes"))
    finally:
        run_replication.REPOSITORY_ROOT = original_root


def test_request_enforces_call_ceiling_and_no_overwrite(tmp_path: Path) -> None:
    _release_fixture(tmp_path)
    original_root = run_replication.REPOSITORY_ROOT
    run_replication.REPOSITORY_ROOT = tmp_path
    try:
        with pytest.raises(run_replication.ReplicationError, match="exceeds MAX_CALLS"):
            run_replication.validate_request(_args(tmp_path, max_calls=2099))

        args = _args(tmp_path)
        (tmp_path / "runs" / args.run_id).mkdir(parents=True)
        with pytest.raises(run_replication.ReplicationError, match="will not be overwritten"):
            run_replication.validate_request(args)
    finally:
        run_replication.REPOSITORY_ROOT = original_root


def test_threshold_scope_is_explicitly_gpt5_only(tmp_path: Path) -> None:
    _release_fixture(tmp_path)
    original_root = run_replication.REPOSITORY_ROOT
    run_replication.REPOSITORY_ROOT = tmp_path
    try:
        with pytest.raises(run_replication.ReplicationError, match="explicit model list"):
            run_replication.validate_request(
                _args(
                    tmp_path,
                    experiment="threshold",
                    models=["gpt-4o-2024-11-20"],
                    max_calls=15,
                )
            )
    finally:
        run_replication.REPOSITORY_ROOT = original_root


def test_recorded_call_count_includes_retries(tmp_path: Path) -> None:
    audit_path = tmp_path / "query_audit.csv"
    with audit_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["row_id", "attempts"])
        writer.writeheader()
        writer.writerows(
            [
                {"row_id": "lr_0001", "attempts": 1},
                {"row_id": "lr_0002", "attempts": 3},
            ]
        )
    assert run_replication._actual_call_count(tmp_path) == 4


def test_run_id_sha_must_match_current_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _release_fixture(tmp_path)
    monkeypatch.setattr(run_replication, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(
        run_replication,
        "_current_commit_sha",
        lambda _repository: "bbbbbbb" + ("0" * 33),
    )
    with pytest.raises(run_replication.ReplicationError, match="does not match current HEAD"):
        run_replication.validate_request(_args(tmp_path))


def test_runs_root_cannot_escape_repository_runs(tmp_path: Path) -> None:
    _release_fixture(tmp_path)
    original_root = run_replication.REPOSITORY_ROOT
    run_replication.REPOSITORY_ROOT = tmp_path
    try:
        with pytest.raises(run_replication.ReplicationError, match="restricted"):
            run_replication.validate_request(_args(tmp_path, runs_root=tmp_path / "results" / "reference"))
    finally:
        run_replication.REPOSITORY_ROOT = original_root


def test_symlinked_runs_root_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _release_fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "runs").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(run_replication, "REPOSITORY_ROOT", tmp_path)
    with pytest.raises(run_replication.ReplicationError, match="must not contain symlinks"):
        run_replication.validate_request(_args(tmp_path))


def test_stage_uses_head_blobs_even_if_worktree_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    notebook_path = tmp_path / "lr_scraper_estimator.ipynb"
    input_path = tmp_path / "data.csv"
    prompt_path = tmp_path / "prompt.json"
    notebook_path.write_text("working notebook\n", encoding="utf-8")
    input_path.write_text("row_id\nworking\n", encoding="utf-8")
    prompt_path.write_text('{"source":"working"}\n', encoding="utf-8")
    committed = {
        "lr_scraper_estimator.ipynb": b"committed notebook\n",
        "data.csv": b"row_id\nlr_0001\n",
        "prompt.json": b'{"source":"HEAD"}\n',
    }
    seen: list[tuple[str, str]] = []

    def fake_read(_repository: Path, commit: str, relative: Path) -> bytes:
        seen.append((commit, relative.as_posix()))
        return committed[relative.as_posix()]

    experiments = dict(run_replication.EXPERIMENTS)
    experiments["main"] = {**experiments["main"], "expected_rows": 1}
    monkeypatch.setattr(run_replication, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(run_replication, "EXPERIMENTS", experiments)
    monkeypatch.setattr(run_replication, "_read_git_blob", fake_read)
    plan = {
        "experiment": "main",
        "git_commit": "abcdef1" + ("0" * 33),
        "models": ("gpt-5",),
        "max_calls": 1,
        "notebook_path": notebook_path,
        "input_path": input_path,
        "prompt_path": prompt_path,
    }
    staged = run_replication._stage_head_artifacts(plan, tmp_path / "stage")
    assert Path(staged["staged_notebook_path"]).read_bytes() == committed["lr_scraper_estimator.ipynb"]
    assert Path(staged["staged_input_path"]).read_bytes() == committed["data.csv"]
    assert Path(staged["staged_prompt_path"]).read_bytes() == committed["prompt.json"]
    assert len(seen) == 3

    notebook_path.write_text("changed again\n", encoding="utf-8")
    run_replication._verify_staged_artifacts(staged)


def test_dirty_worktree_blocks_replication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _release_fixture(tmp_path)
    monkeypatch.setattr(run_replication, "REPOSITORY_ROOT", tmp_path)

    def reject_dirty(_repository: Path) -> None:
        raise run_replication.ReplicationError("Live replication requires a clean Git worktree")

    monkeypatch.setattr(run_replication, "_require_clean_worktree", reject_dirty)
    with pytest.raises(run_replication.ReplicationError, match="clean Git worktree"):
        run_replication.validate_request(_args(tmp_path))


def test_run_manifest_records_commit_environment_calls_and_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_replication, "REPOSITORY_ROOT", tmp_path)
    run_dir = tmp_path / "runs" / "2026-07-10_validation_abcdef1"
    run_dir.mkdir(parents=True)
    input_path = tmp_path / "data.csv"
    input_path.write_text("row_id\nlr_0001\n", encoding="utf-8")
    prompt_path = tmp_path / "prompt.json"
    prompt_path.write_text("{}\n", encoding="utf-8")
    notebook_path = tmp_path / "lr_scraper_estimator.ipynb"
    notebook_path.write_text("{}\n", encoding="utf-8")
    (run_dir / "raw_outputs.csv").write_text("row_id,value\nlr_0001,2.0\n", encoding="utf-8")
    (run_dir / "query_audit.csv").write_text("row_id,attempts\nlr_0001,1\n", encoding="utf-8")
    executed = tmp_path / "executed.ipynb"
    executed.write_text("{}\n", encoding="utf-8")
    plan = {
        "run_id": run_dir.name,
        "git_commit": "abcdef1" + ("0" * 33),
        "experiment": "main",
        "notebook_path": notebook_path,
        "models": run_replication.MANUSCRIPT_MODELS,
        "row_count": 1,
        "call_count": 3,
        "max_calls": 4,
        "run_dir": run_dir,
        "input_path": input_path,
        "prompt_path": prompt_path,
    }
    plan = _with_staged_artifacts(plan, tmp_path)
    run_replication._write_run_metadata(plan, executed)
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["git_commit"] == plan["git_commit"]
    assert manifest["status"] == "completed"
    assert manifest["actual_api_calls"] == 1
    assert manifest["started_at_utc"] == plan["started_at_utc"]
    assert manifest["completed_at_utc"] >= manifest["started_at_utc"]
    assert manifest["notebook_sha256"] == plan["notebook_sha256"]
    assert manifest["input_sha256"] == plan["input_sha256"]
    assert manifest["prompt_sha256"] == plan["prompt_sha256"]
    assert manifest["software_environment"]["python"]
    assert "raw_outputs.csv" in manifest["outputs_sha256"]
    assert manifest["query_settings"]["models"]["gpt-4o-2024-11-20"]["temperature"] == 0.2
    assert manifest["query_settings"]["models"]["gpt-5"]["reasoning_effort"] == "medium"
    assert (run_dir / "SHA256SUMS").is_file()


def test_run_metadata_rejects_symlinked_output_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_replication, "REPOSITORY_ROOT", tmp_path)
    run_dir = tmp_path / "runs" / "2026-07-10_validation_abcdef1"
    run_dir.mkdir(parents=True)
    input_path = tmp_path / "data.csv"
    input_path.write_text("row_id\nlr_0001\n", encoding="utf-8")
    prompt_path = tmp_path / "prompt.json"
    prompt_path.write_text("{}\n", encoding="utf-8")
    notebook_path = tmp_path / "lr_scraper_estimator.ipynb"
    notebook_path.write_text("{}\n", encoding="utf-8")
    (run_dir / "query_audit.csv").write_text("row_id,attempts\nlr_0001,1\n", encoding="utf-8")
    outside = tmp_path / "private.txt"
    outside.write_text("must not be hashed\n", encoding="utf-8")
    (run_dir / "raw_outputs.csv").symlink_to(outside)
    plan = _with_staged_artifacts(
        {
            "run_id": run_dir.name,
            "git_commit": "abcdef1" + ("0" * 33),
            "experiment": "main",
            "notebook_path": notebook_path,
            "models": ("gpt-5",),
            "row_count": 1,
            "call_count": 1,
            "max_calls": 1,
            "run_dir": run_dir,
            "input_path": input_path,
            "prompt_path": prompt_path,
        },
        tmp_path,
    )
    with pytest.raises(run_replication.ReplicationError, match="symlinks or special files"):
        run_replication._write_run_metadata(plan, None)
    assert not (run_dir / "run_manifest.json").exists()


def test_atomic_metadata_writer_never_follows_symlinks(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("private\n", encoding="utf-8")
    destination = tmp_path / "run_manifest.json"
    destination.symlink_to(outside)
    with pytest.raises(run_replication.ReplicationError, match="symlink or special output"):
        run_replication._atomic_write_text(destination, "replacement\n")
    assert destination.is_symlink()
    assert outside.read_text(encoding="utf-8") == "private\n"

    destination.unlink()
    predictable = tmp_path / f".{destination.name}.tmp"
    predictable.symlink_to(outside)
    run_replication._atomic_write_text(destination, "replacement\n")
    assert destination.read_text(encoding="utf-8") == "replacement\n"
    assert outside.read_text(encoding="utf-8") == "private\n"
    assert predictable.is_symlink()
    assert not [
        path
        for path in tmp_path.iterdir()
        if path.name.startswith(f".{destination.name}.") and path != predictable
    ]


@pytest.mark.parametrize("mutation", ["existing-directory", "symlink", "dirty-worktree"])
def test_post_stage_mutation_is_rejected_before_credential_access(
    mutation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_replication, "REPOSITORY_ROOT", tmp_path)
    run_dir = tmp_path / "runs" / "2026-07-10_validation_abcdef1"
    input_path = tmp_path / "data.csv"
    input_path.write_text("row_id\nlr_0001\n", encoding="utf-8")
    prompt_path = tmp_path / "prompt.json"
    prompt_path.write_text("{}\n", encoding="utf-8")
    notebook_path = tmp_path / "lr_scraper_estimator.ipynb"
    notebook_path.write_text("{}\n", encoding="utf-8")
    plan = {
        "run_id": run_dir.name,
        "git_commit": "abcdef1" + ("0" * 33),
        "experiment": "main",
        "notebook_path": notebook_path,
        "models": ("gpt-5",),
        "row_count": 1,
        "call_count": 1,
        "max_calls": 1,
        "runs_root": tmp_path / "runs",
        "run_dir": run_dir,
        "input_path": input_path,
        "prompt_path": prompt_path,
    }

    def stage_and_mutate(requested_plan, _stage_root):
        staged = _with_staged_artifacts(requested_plan, tmp_path)
        if mutation == "existing-directory":
            run_dir.mkdir(parents=True)
        elif mutation == "symlink":
            run_dir.parent.mkdir(parents=True)
            outside = tmp_path / "outside-run"
            outside.mkdir()
            run_dir.symlink_to(outside, target_is_directory=True)
        return staged

    monkeypatch.setattr(run_replication, "_stage_head_artifacts", stage_and_mutate)
    if mutation == "dirty-worktree":
        monkeypatch.setattr(
            run_replication,
            "_require_clean_worktree",
            lambda _repository: (_ for _ in ()).throw(
                run_replication.ReplicationError("Live replication requires a clean Git worktree")
            ),
        )

    credential_accessed = False

    def unexpected_load(*_args, **_kwargs):
        nonlocal credential_accessed
        credential_accessed = True
        raise AssertionError("credential loading was reached")

    monkeypatch.setattr(dotenv, "load_dotenv", unexpected_load)
    with pytest.raises(run_replication.ReplicationError):
        run_replication.execute(plan)
    assert not credential_accessed


def test_failed_notebook_run_is_finalized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_replication, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    run_dir = tmp_path / "runs" / "2026-07-10_validation_abcdef1"
    input_path = tmp_path / "data.csv"
    input_path.write_text("row_id\nlr_0001\n", encoding="utf-8")
    prompt_path = tmp_path / "prompt.json"
    prompt_path.write_text("{}\n", encoding="utf-8")
    notebook_path = tmp_path / "lr_scraper_estimator.ipynb"
    notebook_path.write_text("{}\n", encoding="utf-8")
    plan = {
        "run_id": run_dir.name,
        "git_commit": "abcdef1" + ("0" * 33),
        "experiment": "main",
        "notebook_path": notebook_path,
        "models": run_replication.MANUSCRIPT_MODELS,
        "row_count": 1,
        "call_count": 3,
        "max_calls": 4,
        "runs_root": tmp_path / "runs",
        "run_dir": run_dir,
        "input_path": input_path,
        "prompt_path": prompt_path,
    }
    command_count = 0

    monkeypatch.setattr(
        run_replication,
        "_stage_head_artifacts",
        lambda requested_plan, _stage_root: _with_staged_artifacts(requested_plan, tmp_path),
    )

    def fake_run(command, **_kwargs):
        nonlocal command_count
        command_count += 1
        if "nbconvert" in command:
            run_dir.mkdir(parents=True)
            (run_dir / "raw_outputs.csv").write_text("row_id,value\nlr_0001,2.0\n", encoding="utf-8")
            (run_dir / "query_audit.csv").write_text("row_id,attempts\nlr_0001,1\n", encoding="utf-8")
            raise run_replication.subprocess.CalledProcessError(1, command)
        return run_replication.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(run_replication.subprocess, "run", fake_run)
    with pytest.raises(run_replication.subprocess.CalledProcessError):
        run_replication.execute(plan)
    assert command_count == 2
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["failure_message"] == "Notebook execution failed with exit code 1."
    assert manifest["actual_api_calls"] == 1
    assert (run_dir / "prompt_snapshot.json").is_file()
    assert (run_dir / "SHA256SUMS").is_file()


def test_interrupted_notebook_run_is_finalized_with_reserved_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_replication, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    run_dir = tmp_path / "runs" / "2026-07-10_validation_abcdef1"
    input_path = tmp_path / "data.csv"
    input_path.write_text("row_id\nlr_0001\n", encoding="utf-8")
    prompt_path = tmp_path / "prompt.json"
    prompt_path.write_text("{}\n", encoding="utf-8")
    notebook_path = tmp_path / "lr_scraper_estimator.ipynb"
    notebook_path.write_text("{}\n", encoding="utf-8")
    plan = {
        "run_id": run_dir.name,
        "git_commit": "abcdef1" + ("0" * 33),
        "experiment": "main",
        "notebook_path": notebook_path,
        "models": ("gpt-5",),
        "row_count": 1,
        "call_count": 1,
        "max_calls": 1,
        "runs_root": tmp_path / "runs",
        "run_dir": run_dir,
        "input_path": input_path,
        "prompt_path": prompt_path,
    }
    monkeypatch.setattr(
        run_replication,
        "_stage_head_artifacts",
        lambda requested_plan, _stage_root: _with_staged_artifacts(requested_plan, tmp_path),
    )
    command_count = 0

    def fake_run(command, **_kwargs):
        nonlocal command_count
        command_count += 1
        if "nbconvert" in command:
            run_dir.mkdir(parents=True)
            (run_dir / "query_audit.csv").write_text(
                "row_id,attempts,final_status\nlr_0001,1,in_progress\n",
                encoding="utf-8",
            )
            raise KeyboardInterrupt
        return run_replication.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(run_replication.subprocess, "run", fake_run)
    with pytest.raises(KeyboardInterrupt):
        run_replication.execute(plan)
    assert command_count == 2
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["failure_message"] == "Notebook execution was interrupted."
    assert manifest["actual_api_calls"] == 1
    assert (run_dir / "prompt_snapshot.json").is_file()
    assert (run_dir / "SHA256SUMS").is_file()


def test_dry_run_never_loads_key_or_executes_notebook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _release_fixture(tmp_path)
    monkeypatch.setattr(run_replication, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def unexpected_execute(_plan):
        raise AssertionError("dry run attempted notebook execution")

    monkeypatch.setattr(run_replication, "execute", unexpected_execute)
    exit_code = run_replication.main(
        [
            "--run-id",
            "2026-07-10_validation_abcdef1",
            "--experiment",
            "main",
            "--models",
            *run_replication.MANUSCRIPT_MODELS,
            "--max-calls",
            "2100",
            "--confirm-live-api",
            "YES",
            "--runs-root",
            str(tmp_path / "runs"),
            "--dry-run",
        ]
    )
    assert exit_code == 0
    assert not (tmp_path / "runs").exists()
    assert "2100" in capsys.readouterr().out
