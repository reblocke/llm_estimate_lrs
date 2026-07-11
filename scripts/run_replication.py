#!/usr/bin/env python3
"""Launch a guarded live replication in an immutable run directory.

This launcher performs all validation before an API-capable notebook is
executed.  It does not import an API client and its ``--dry-run`` mode never
executes a notebook or accesses the network.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})_"
    r"(?P<description>[a-z0-9]+(?:-[a-z0-9]+)*)_"
    r"(?P<sha>[0-9a-f]{7,12})$"
)

MANUSCRIPT_MODELS = (
    "gpt-4o-2024-11-20",
    "o3-2025-04-16",
    "gpt-5",
)
SUPPORTED_MODELS = (
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4.1-2025-04-14",
    "gpt-4.1-mini-2025-04-14",
    "gpt-4.1-nano-2025-04-14",
    "gpt-4o-2024-11-20",
    "gpt-4o-mini-2024-07-18",
    "o3-2025-04-16",
    "o3-mini-2025-01-31",
    "o4-mini-2025-04-16",
)

EXPERIMENTS = {
    "main": {
        "notebook": "lr_scraper_estimator.ipynb",
        "input": "data/curated/diagnostic_lrs_manuscript_v1.csv",
        "prompt": "prompts/main_estimator_v1.json",
        "expected_rows": 700,
    },
    "threshold": {
        "notebook": "threshold_perturbation_sensitivity_analysis.ipynb",
        "input": ("data/model_outputs/threshold_perturbation_v1/threshold_perturbation_cases.csv"),
        "prompt": "prompts/threshold_perturbation_v1.json",
        "expected_rows": 15,
    },
}


class ReplicationError(RuntimeError):
    """Raised before execution when a replication request is unsafe."""


def parse_models(values: list[str]) -> tuple[str, ...]:
    """Normalize whitespace- or comma-separated model arguments."""
    models: list[str] = []
    for value in values:
        models.extend(part.strip() for part in value.split(",") if part.strip())
    if not models:
        raise ReplicationError("At least one explicit model is required.")
    if len(models) != len(set(models)):
        raise ReplicationError("Model names must not be repeated.")
    unsupported = sorted(set(models).difference(SUPPORTED_MODELS))
    if unsupported:
        raise ReplicationError(f"Unsupported model(s): {', '.join(unsupported)}")
    return tuple(models)


def validate_run_id(run_id: str) -> None:
    """Enforce the documented date-description-short-SHA run convention."""
    match = RUN_ID_PATTERN.fullmatch(run_id)
    if match is None:
        raise ReplicationError("RUN_ID must match YYYY-MM-DD_short-description_7-to-12-hex-sha.")
    try:
        datetime.strptime(match.group("date"), "%Y-%m-%d")
    except ValueError as exc:
        raise ReplicationError("RUN_ID begins with an invalid calendar date.") from exc


def _current_commit_sha(repository: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip().lower()
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ReplicationError("A valid Git HEAD is required for a versioned replication run.")
    return commit


def _require_clean_worktree(repository: Path) -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ReplicationError("The Git worktree state could not be verified.")
    if result.stdout.strip():
        raise ReplicationError("Live replication requires a clean Git worktree so RUN_ID identifies the executed code.")


def csv_row_count(path: Path) -> int:
    """Count data rows without importing analytical dependencies."""
    if not path.is_file():
        raise ReplicationError(f"Required replication input is missing: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        try:
            next(reader)
        except StopIteration as exc:
            raise ReplicationError(f"Replication input is empty: {path}") from exc
        return sum(1 for row in reader if any(field.strip() for field in row))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(_read_regular_bytes(path)).hexdigest()


def _lexical_absolute(path: Path) -> Path:
    """Return an absolute normalized path without resolving symlinks."""
    return Path(os.path.abspath(os.fspath(path)))


def _reject_symlink_components(path: Path) -> None:
    """Reject any existing symlink component in a live-output path."""
    absolute = _lexical_absolute(path)
    candidate = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        candidate /= component
        if candidate.is_symlink():
            raise ReplicationError(f"Live replication paths must not contain symlinks: {candidate}")


def _regular_files_under(root: Path) -> list[Path]:
    """List run files without following symlinks or accepting special files."""
    _reject_symlink_components(root)
    try:
        root_mode = root.lstat().st_mode
    except FileNotFoundError as exc:
        raise ReplicationError(f"Replication run directory is missing: {root}") from exc
    if not stat.S_ISDIR(root_mode):
        raise ReplicationError(f"Replication run path is not a regular directory: {root}")

    files: list[Path] = []
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in directory_names:
            child = directory_path / name
            if not stat.S_ISDIR(child.lstat().st_mode):
                raise ReplicationError(f"Replication outputs must not contain symlinks or special files: {child}")
        for name in file_names:
            child = directory_path / name
            if not stat.S_ISREG(child.lstat().st_mode):
                raise ReplicationError(f"Replication outputs must not contain symlinks or special files: {child}")
            files.append(child)
    return sorted(files)


def _read_regular_bytes(path: Path) -> bytes:
    """Read a regular file through a no-follow descriptor."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ReplicationError(f"Could not safely open regular file: {path}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ReplicationError(f"Expected a regular file: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _atomic_write_bytes(destination: Path, payload: bytes) -> None:
    """Durably replace a regular file without following a destination symlink."""
    destination = _lexical_absolute(destination)
    parent = destination.parent
    _reject_symlink_components(parent)
    try:
        parent_mode = parent.lstat().st_mode
    except FileNotFoundError as exc:
        raise ReplicationError(f"Output parent directory is missing: {parent}") from exc
    if not stat.S_ISDIR(parent_mode):
        raise ReplicationError(f"Output parent must be a regular directory: {parent}")

    def reject_nonregular_destination() -> None:
        if os.path.lexists(destination) and not stat.S_ISREG(destination.lstat().st_mode):
            raise ReplicationError(f"Refusing to replace a symlink or special output file: {destination}")

    reject_nonregular_destination()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=parent,
    )
    temporary = Path(temporary_name)
    descriptor_open = True
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor_open = False
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        reject_nonregular_destination()
        os.replace(temporary, destination)
    finally:
        if descriptor_open:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _atomic_write_text(destination: Path, text: str) -> None:
    _atomic_write_bytes(destination, text.encode("utf-8"))


def _atomic_copy_regular(source: Path, destination: Path) -> None:
    _atomic_write_bytes(destination, _read_regular_bytes(source))


def _read_git_blob(repository: Path, commit: str, relative_path: Path) -> bytes:
    """Read one regular tracked file exactly as stored in a Git commit."""
    git_path = relative_path.as_posix()
    tree = subprocess.run(
        ["git", "ls-tree", commit, "--", git_path],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    line = tree.stdout.rstrip("\n")
    if tree.returncode != 0 or not line or "\t" not in line:
        raise ReplicationError(f"Required replication artifact is not tracked at {commit[:12]}: {git_path}")
    header, listed_path = line.split("\t", 1)
    fields = header.split()
    if len(fields) != 3 or listed_path != git_path:
        raise ReplicationError(f"Could not verify the Git object for replication artifact: {git_path}")
    mode, object_type, _object_id = fields
    if object_type != "blob" or mode not in {"100644", "100755"}:
        raise ReplicationError(f"Replication artifacts must be regular tracked files: {git_path}")
    blob = subprocess.run(
        ["git", "cat-file", "blob", f"{commit}:{git_path}"],
        cwd=repository,
        check=False,
        capture_output=True,
    )
    if blob.returncode != 0:
        raise ReplicationError(f"Could not read the Git object for replication artifact: {git_path}")
    return blob.stdout


def _stage_head_artifacts(plan: dict[str, object], stage_root: Path) -> dict[str, object]:
    """Materialize immutable notebook, input, and prompt blobs from the planned HEAD."""
    staged = dict(plan)
    commit = str(plan["git_commit"])
    for artifact in ("notebook", "input", "prompt"):
        source = _lexical_absolute(Path(plan[f"{artifact}_path"]))
        try:
            relative = source.relative_to(REPOSITORY_ROOT)
        except ValueError as exc:
            raise ReplicationError(f"Replication {artifact} must be inside the repository.") from exc
        payload = _read_git_blob(REPOSITORY_ROOT, commit, relative)
        destination = stage_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        staged[f"staged_{artifact}_path"] = destination
        staged[f"{artifact}_sha256"] = hashlib.sha256(payload).hexdigest()

    staged_rows = csv_row_count(Path(staged["staged_input_path"]))
    expected_rows = int(EXPERIMENTS[str(plan["experiment"])]["expected_rows"])
    if staged_rows != expected_rows:
        raise ReplicationError(
            f"Expected {expected_rows} input rows in the staged HEAD artifact, found {staged_rows}."
        )
    staged_calls = staged_rows * len(tuple(plan["models"]))
    if staged_calls > int(plan["max_calls"]):
        raise ReplicationError(f"Planned call count {staged_calls} exceeds MAX_CALLS={plan['max_calls']}.")
    staged["row_count"] = staged_rows
    staged["call_count"] = staged_calls
    return staged


def _verify_staged_artifacts(plan: dict[str, object]) -> None:
    """Fail if any staged execution artifact changed during the run."""
    for artifact in ("notebook", "input", "prompt"):
        path = Path(plan[f"staged_{artifact}_path"])
        if sha256_file(path) != plan[f"{artifact}_sha256"]:
            raise ReplicationError(f"The staged {artifact} changed during execution: {path}")


def _revalidate_before_credentials(plan: dict[str, object]) -> None:
    """Repeat mutable-state gates after staging and before credential access."""
    if _current_commit_sha(REPOSITORY_ROOT) != plan["git_commit"]:
        raise ReplicationError("Git HEAD changed after replication artifacts were staged.")
    _require_clean_worktree(REPOSITORY_ROOT)
    _verify_staged_artifacts(plan)

    runs_root = _lexical_absolute(Path(plan["runs_root"]))
    expected_runs_root = _lexical_absolute(REPOSITORY_ROOT / "runs")
    if runs_root != expected_runs_root:
        raise ReplicationError("Live replication outputs are restricted to the repository runs/ directory.")
    expected_run_dir = _lexical_absolute(runs_root / str(plan["run_id"]))
    run_dir = _lexical_absolute(Path(plan["run_dir"]))
    if run_dir != expected_run_dir or run_dir.parent != runs_root:
        raise ReplicationError("RUN_ID must resolve to one direct child of the runs root.")
    _reject_symlink_components(run_dir)
    if os.path.lexists(run_dir):
        raise ReplicationError(f"Run directory already exists and will not be overwritten: {run_dir}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and launch a new live model replication.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--experiment", choices=sorted(EXPERIMENTS), required=True)
    parser.add_argument(
        "--models",
        nargs="+",
        required=True,
        help="Explicit model IDs, separated by spaces or commas.",
    )
    parser.add_argument("--max-calls", required=True, type=int)
    parser.add_argument(
        "--confirm-live-api",
        required=True,
        help="Must be exactly YES after reviewing the printed call count.",
    )
    parser.add_argument(
        "--runs-root",
        type=Path,
        help="Optional explicit path; it must resolve to this repository's runs/ directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the execution plan without loading credentials.",
    )
    return parser


def validate_request(args: argparse.Namespace) -> dict[str, object]:
    validate_run_id(args.run_id)
    if args.confirm_live_api != "YES":
        raise ReplicationError("Live API confirmation must be exactly YES.")
    if args.max_calls <= 0:
        raise ReplicationError("MAX_CALLS must be a positive integer.")

    models = parse_models(args.models)
    if args.experiment == "threshold" and models != ("gpt-5",):
        raise ReplicationError("The threshold experiment is defined for the explicit model list: gpt-5.")

    experiment = EXPERIMENTS[args.experiment]
    input_path = REPOSITORY_ROOT / str(experiment["input"])
    prompt_path = REPOSITORY_ROOT / str(experiment["prompt"])
    notebook_path = REPOSITORY_ROOT / str(experiment["notebook"])
    for required in (prompt_path, notebook_path):
        if not required.is_file():
            raise ReplicationError(f"Required replication artifact is missing: {required}")

    row_count = csv_row_count(input_path)
    expected_rows = int(experiment["expected_rows"])
    if row_count != expected_rows:
        raise ReplicationError(f"Expected {expected_rows} input rows for {args.experiment}, found {row_count}.")

    call_count = row_count * len(models)
    if call_count > args.max_calls:
        raise ReplicationError(f"Planned call count {call_count} exceeds MAX_CALLS={args.max_calls}.")

    commit_sha = _current_commit_sha(REPOSITORY_ROOT)
    run_sha = RUN_ID_PATTERN.fullmatch(args.run_id).group("sha")
    if not commit_sha.startswith(run_sha):
        raise ReplicationError(f"RUN_ID SHA suffix {run_sha} does not match current HEAD {commit_sha[:12]}.")
    _require_clean_worktree(REPOSITORY_ROOT)

    expected_runs_root = _lexical_absolute(REPOSITORY_ROOT / "runs")
    requested_runs_root = _lexical_absolute(args.runs_root) if args.runs_root else expected_runs_root
    if requested_runs_root != expected_runs_root:
        raise ReplicationError("Live replication outputs are restricted to the repository runs/ directory.")
    runs_root = expected_runs_root
    run_dir = _lexical_absolute(runs_root / args.run_id)
    if run_dir.parent != runs_root:
        raise ReplicationError("RUN_ID must resolve to one direct child of the runs root.")
    _reject_symlink_components(run_dir)
    if os.path.lexists(run_dir):
        raise ReplicationError(f"Run directory already exists and will not be overwritten: {run_dir}")

    return {
        "experiment": args.experiment,
        "run_id": args.run_id,
        "models": models,
        "row_count": row_count,
        "call_count": call_count,
        "max_calls": args.max_calls,
        "git_commit": commit_sha,
        "runs_root": runs_root,
        "run_dir": run_dir,
        "notebook_path": notebook_path,
        "input_path": input_path,
        "prompt_path": prompt_path,
    }


def print_plan(plan: dict[str, object]) -> None:
    print("Live replication plan")
    print(f"  run ID:      {plan['run_id']}")
    print(f"  experiment:  {plan['experiment']}")
    print(f"  models:      {', '.join(plan['models'])}")
    print(f"  input rows:  {plan['row_count']}")
    print(f"  API calls:   {plan['call_count']}")
    print(f"  call ceiling: {plan['max_calls']}")
    print(f"  output:      {plan['run_dir']}")


def _copy_threshold_outputs(run_dir: Path) -> None:
    raw_path = run_dir / "threshold_perturbation_raw.csv"
    audit_path = run_dir / "query_audit.csv"
    canonical_raw_path = run_dir / "raw_outputs.csv"
    if raw_path.is_file():
        _atomic_copy_regular(raw_path, canonical_raw_path)
        if not audit_path.is_file():
            with io.StringIO(_read_regular_bytes(raw_path).decode("utf-8-sig"), newline="") as source:
                reader = csv.DictReader(source)
                fields = [
                    "case_id",
                    "variant_order",
                    "model",
                    "attempts",
                    "error_status",
                    "error_message",
                    "queried_at",
                    "started_at_utc",
                    "completed_at_utc",
                ]
                output = io.StringIO(newline="")
                writer = csv.DictWriter(output, fieldnames=fields)
                writer.writeheader()
                for row in reader:
                    audit_row = {field: row.get(field, "") for field in fields}
                    audit_row["attempts"] = audit_row["attempts"] or "1"
                    audit_row["started_at_utc"] = audit_row["started_at_utc"] or audit_row["queried_at"]
                    writer.writerow(audit_row)
                _atomic_write_text(audit_path, output.getvalue())


def _actual_call_count(run_dir: Path, *, allow_missing: bool = False) -> int:
    audit_path = run_dir / "query_audit.csv"
    if not os.path.lexists(audit_path):
        if allow_missing:
            return 0
        raise ReplicationError(f"The completed notebook did not write its query audit: {audit_path}")
    with io.StringIO(_read_regular_bytes(audit_path).decode("utf-8-sig"), newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ReplicationError("The completed notebook wrote an empty query audit.")
    if "attempts" in rows[0]:
        try:
            return sum(int(row["attempts"]) for row in rows)
        except (TypeError, ValueError) as exc:
            raise ReplicationError("The query audit contains an invalid attempt count.") from exc
    return len(rows)


def _effective_model_settings(model: str) -> dict[str, object | None]:
    reasoning = model.startswith("gpt-5") or model.startswith(("o3", "o4"))
    return {
        "reasoning_effort": "medium" if reasoning else None,
        "temperature": None if reasoning else 0.2,
        "text_verbosity": "low" if model.startswith("gpt-5") else None,
    }


def _software_environment() -> dict[str, object]:
    packages: dict[str, str] = {}
    for package in ("openai", "pandas", "pydantic", "nbconvert", "ipykernel"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = "not-installed"
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": packages,
    }


def _write_run_metadata(
    plan: dict[str, object],
    executed_notebook: Path | None,
    *,
    status: str = "completed",
    failure_message: str | None = None,
) -> None:
    run_dir = Path(plan["run_dir"])
    _reject_symlink_components(run_dir)
    _verify_staged_artifacts(plan)
    _regular_files_under(run_dir)
    prompt_path = Path(plan["staged_prompt_path"])
    prompt_snapshot = run_dir / "prompt_snapshot.json"
    _atomic_copy_regular(prompt_path, prompt_snapshot)

    if plan["experiment"] == "threshold":
        _copy_threshold_outputs(run_dir)

    actual_calls = _actual_call_count(run_dir, allow_missing=status == "failed")
    if actual_calls > int(plan["max_calls"]):
        raise ReplicationError(f"Recorded API calls {actual_calls} exceed MAX_CALLS={plan['max_calls']}.")

    analysis_dir = run_dir / "analysis_outputs"
    analysis_dir.mkdir(exist_ok=True)
    if executed_notebook is not None and executed_notebook.is_file():
        executed_target = analysis_dir / executed_notebook.name
        _atomic_copy_regular(executed_notebook, executed_target)
        executed_notebook.unlink()

    output_paths = [
        path for path in _regular_files_under(run_dir) if path.name not in {"run_manifest.json", "SHA256SUMS"}
    ]
    output_hashes = {path.relative_to(run_dir).as_posix(): sha256_file(path) for path in output_paths}

    completed_at_utc = datetime.now(UTC).isoformat()
    started_at_utc = str(plan["started_at_utc"])
    manifest = {
        "run_id": plan["run_id"],
        "status": status,
        "failure_message": failure_message,
        "git_commit": plan["git_commit"],
        "experiment": plan["experiment"],
        "notebook": Path(plan["notebook_path"]).name,
        "models": list(plan["models"]),
        "input_rows": plan["row_count"],
        "planned_api_calls": plan["call_count"],
        "actual_api_calls": actual_calls,
        "max_calls": plan["max_calls"],
        "query_settings": {
            "prompt_snapshot": "prompt_snapshot.json",
            "maximum_attempts_per_row": 8 if plan["experiment"] == "main" else 1,
            "output_directory_overwrite": False,
            "models": {model: _effective_model_settings(model) for model in plan["models"]},
        },
        "started_at_utc": started_at_utc,
        "completed_at_utc": completed_at_utc,
        "created_at_utc": started_at_utc,
        "notebook_file": str(Path(plan["notebook_path"]).relative_to(REPOSITORY_ROOT)),
        "notebook_sha256": plan["notebook_sha256"],
        "input_file": str(Path(plan["input_path"]).relative_to(REPOSITORY_ROOT)),
        "input_sha256": plan["input_sha256"],
        "prompt_file": str(Path(plan["prompt_path"]).relative_to(REPOSITORY_ROOT)),
        "prompt_sha256": plan["prompt_sha256"],
        "software_environment": _software_environment(),
        "outputs_sha256": output_hashes,
        "checksum_file": "SHA256SUMS",
        "accepted_paper_artifact": False,
    }
    manifest_path = run_dir / "run_manifest.json"
    _atomic_write_text(manifest_path, json.dumps(manifest, indent=2) + "\n")

    checksum_paths = [path for path in _regular_files_under(run_dir) if path.name != "SHA256SUMS"]
    checksum_lines = [f"{sha256_file(path)}  {path.relative_to(run_dir).as_posix()}" for path in checksum_paths]
    _atomic_write_text(run_dir / "SHA256SUMS", "\n".join(checksum_lines) + "\n")


def execute(plan: dict[str, object]) -> None:
    with tempfile.TemporaryDirectory(prefix="replication-notebook-") as temp_dir:
        stage_root = Path(temp_dir) / "head"
        execution_plan = _stage_head_artifacts(plan, stage_root)
        _revalidate_before_credentials(execution_plan)

        # Load the local key only after exact HEAD blobs have been staged and
        # the run ID, model scope, call ceiling, and no-overwrite checks pass.
        from dotenv import load_dotenv

        load_dotenv(REPOSITORY_ROOT / ".env")
        if not os.getenv("OPENAI_API_KEY"):
            raise ReplicationError("OPENAI_API_KEY is required for execution; use --dry-run to validate only.")

        runs_root = Path(execution_plan["runs_root"])
        _reject_symlink_components(runs_root)
        runs_root.mkdir(parents=True, exist_ok=True)
        _reject_symlink_components(runs_root)
        environment = os.environ.copy()
        environment.update(
            {
                "LLM_LR_LIVE_REPLICATION": "1",
                "LLM_LR_RUN_ID": str(execution_plan["run_id"]),
                "LLM_LR_MODELS": ",".join(execution_plan["models"]),
                "LLM_LR_MAX_CALLS": str(execution_plan["max_calls"]),
                "LLM_LR_CONFIRM_LIVE_API": "YES",
                "LLM_LR_RUNS_ROOT": str(runs_root),
                "LLM_LR_GIT_COMMIT": str(execution_plan["git_commit"]),
                "LLM_LR_REPOSITORY_ROOT": str(REPOSITORY_ROOT),
                "LLM_LR_INPUT_FILE": str(execution_plan["staged_input_path"]),
            }
        )
        execution_plan["started_at_utc"] = datetime.now(UTC).isoformat()

        kernel_prefix = Path(temp_dir) / "kernel"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "ipykernel",
                "install",
                "--prefix",
                str(kernel_prefix),
                "--name",
                "llm-estimate-lrs-replication",
                "--display-name",
                "Python (llm-estimate-lrs replication)",
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            check=True,
        )
        temporary_jupyter_path = str(kernel_prefix / "share" / "jupyter")
        existing_jupyter_path = environment.get("JUPYTER_PATH")
        environment["JUPYTER_PATH"] = (
            temporary_jupyter_path
            if not existing_jupyter_path
            else temporary_jupyter_path + os.pathsep + existing_jupyter_path
        )
        executed_name = f"{Path(execution_plan['notebook_path']).stem}_executed.ipynb"
        command = [
            sys.executable,
            "-m",
            "jupyter",
            "nbconvert",
            "--to",
            "notebook",
            "--execute",
            "--ExecutePreprocessor.timeout=-1",
            "--ExecutePreprocessor.kernel_name=llm-estimate-lrs-replication",
            "--output",
            executed_name,
            "--output-dir",
            temp_dir,
            str(execution_plan["staged_notebook_path"]),
        ]
        run_dir = Path(execution_plan["run_dir"])
        executed_path = Path(temp_dir) / executed_name
        try:
            subprocess.run(command, cwd=REPOSITORY_ROOT, env=environment, check=True)
        except subprocess.CalledProcessError as exc:
            if run_dir.is_dir():
                _write_run_metadata(
                    execution_plan,
                    executed_path if executed_path.is_file() else None,
                    status="failed",
                    failure_message=f"Notebook execution failed with exit code {exc.returncode}.",
                )
            raise
        except KeyboardInterrupt:
            if run_dir.is_dir():
                _write_run_metadata(
                    execution_plan,
                    executed_path if executed_path.is_file() else None,
                    status="failed",
                    failure_message="Notebook execution was interrupted.",
                )
            raise
        if not run_dir.is_dir():
            raise ReplicationError("The notebook completed without creating the guarded run directory.")
        _write_run_metadata(execution_plan, executed_path)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = validate_request(args)
        print_plan(plan)
        if args.dry_run:
            print("Dry run complete; no credential was loaded and no notebook was executed.")
            return 0
        execute(plan)
    except (ReplicationError, subprocess.CalledProcessError) as exc:
        print(f"Replication blocked: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Replication interrupted; any created run was finalized as failed.", file=sys.stderr)
        return 130
    print(f"Replication complete: {plan['run_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
