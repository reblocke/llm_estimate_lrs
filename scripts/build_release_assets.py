#!/usr/bin/env python3
"""Build the complete GitHub release-asset set from a clean reviewed tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import nbformat

if __package__:
    from scripts.build_release_archive import (
        FIXED_ZIP_TIME,
        GitBlob,
        build_archive,
        read_git_blob,
        repository_blobs,
        write_bytes_atomically,
        write_zip_atomically,
    )
    from scripts.generate_release_attestation import generate_attestation
    from scripts.git_safety import (
        no_lazy_fetch_environment,
        require_complete_local_objects,
        require_full_local_clone,
    )
else:
    from build_release_archive import (
        FIXED_ZIP_TIME,
        GitBlob,
        build_archive,
        read_git_blob,
        repository_blobs,
        write_bytes_atomically,
        write_zip_atomically,
    )
    from generate_release_attestation import generate_attestation
    from git_safety import (
        no_lazy_fetch_environment,
        require_complete_local_objects,
        require_full_local_clone,
    )

REFERENCE_MEMBERS = (
    "checksums/SHA256SUMS",
    "data/curated/diagnostic_lrs_manuscript_v1.csv",
    "data/model_outputs/auxiliary_gpt-4.1_outputs_v1.csv",
    "data/model_outputs/manuscript_model_outputs_v1.csv",
    "data/model_outputs/manuscript_query_run_v1.csv",
    "data/model_outputs/threshold_perturbation_v1/README.md",
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_cases.csv",
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_raw.csv",
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_reviewer_table.csv",
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_summary.csv",
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_summary.md",
    "data/provenance/curation_log_v1.csv",
    "data/provenance/provenance_gaps_v1.csv",
    "data/provenance/source_crosswalk_v1.csv",
    "manifests/manuscript_run_v1.json",
    "results/reference/README.md",
    "results/reference/agreement_metrics.csv",
    "results/reference/calibration_metrics.csv",
    "results/reference/category_counts.csv",
    "results/reference/coverage_intervals.csv",
    "results/reference/evidence_direction_tests.csv",
    "results/reference/feature_type_counts.csv",
    "results/reference/kappa_metrics.csv",
    "results/reference/laboratory_discrepancy_flags.json",
    "results/reference/main_metrics.json",
    "results/reference/pairwise_model_comparisons.csv",
    "results/reference/reliability_metrics.csv",
    "results/reference/reliability_zone_metrics.csv",
)

NOTEBOOKS = ("data_analysis.ipynb", "supplementary_analyses.ipynb")
WORKBOOKS = ("NNT_LRs_08-26-2025.xlsx", "nnt_lrs_with_estimated.xlsx")
VERIFICATION_INPUTS = (*WORKBOOKS, *NOTEBOOKS)
EXPECTED_ASSET_PATHS = {
    "SHA256SUMS",
    "llm-estimate-lrs-v1.0.0.zip",
    "notebooks/data_analysis.executed.ipynb",
    "notebooks/supplementary_analyses.executed.ipynb",
    "reference-tables-v1.0.0.zip",
    "release-attestation.json",
    "validation-report.json",
}


class ReleaseAssetError(RuntimeError):
    """Raised when release assets cannot be built safely."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        env=no_lazy_fetch_environment(),
    ).stdout.strip()


def require_clean_ref(repository: Path, ref: str) -> str:
    """Require a clean governance checkout and resolve the candidate ref once."""
    status = _git(repository, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise ReleaseAssetError("Release assets require a clean tracked and untracked working tree.")
    return _git(repository, "rev-parse", f"{ref}^{{commit}}")


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _reject_symlink_components(path: Path) -> None:
    path = _lexical_absolute(path)
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        if current.is_symlink():
            raise ReleaseAssetError(f"Release-asset path contains a symbolic link: {current}")


def _zip_blob(archive: zipfile.ZipFile, repository: Path, blob: GitBlob) -> None:
    info = zipfile.ZipInfo(blob.path, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    permissions = 0o755 if blob.mode == "100755" else 0o644
    info.external_attr = (stat.S_IFREG | permissions) << 16
    archive.writestr(info, read_git_blob(repository, blob.object_id), compress_type=zipfile.ZIP_STORED)


def build_reference_archive(repository: Path, output: Path, ref: str = "HEAD") -> Path:
    repository = repository.resolve()
    unresolved_output = _lexical_absolute(output)
    _reject_symlink_components(unresolved_output.parent)
    output = unresolved_output
    blob_map = {blob.path: blob for blob in repository_blobs(repository, ref)}
    missing = [relative for relative in REFERENCE_MEMBERS if relative not in blob_map]
    if missing:
        raise ReleaseAssetError(f"Reference archive inputs are missing: {missing}")
    blobs = [blob_map[relative] for relative in REFERENCE_MEMBERS]

    def write_members(archive: zipfile.ZipFile) -> None:
        for blob in blobs:
            _zip_blob(archive, repository, blob)

    return write_zip_atomically(output, REFERENCE_MEMBERS, write_members)


def _network_guard_source() -> str:
    return """\
import ipaddress
import socket

import matplotlib.figure
import matplotlib.pyplot as plt

_original_connect = socket.socket.connect
_original_getaddrinfo = socket.getaddrinfo

def _loopback(host):
    if host in {None, '', 'localhost'}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False

def _guarded_connect(instance, address):
    if instance.family in {socket.AF_INET, socket.AF_INET6} and not _loopback(address[0]):
        raise RuntimeError('External network access is blocked during notebook verification.')
    return _original_connect(instance, address)

def _guarded_getaddrinfo(host, *args, **kwargs):
    if not _loopback(host):
        raise RuntimeError('External name resolution is blocked during notebook verification.')
    return _original_getaddrinfo(host, *args, **kwargs)

socket.socket.connect = _guarded_connect
socket.getaddrinfo = _guarded_getaddrinfo

def _suppress_figure_file(*args, **kwargs):
    return None

matplotlib.figure.Figure.savefig = _suppress_figure_file
plt.savefig = _suppress_figure_file
"""


def _scrub_execution_metadata(path: Path, workspace: Path) -> None:
    notebook = nbformat.read(path, as_version=4)
    workspace_paths = {str(workspace), str(workspace.resolve())}

    def scrub(value: str) -> str:
        for workspace_path in workspace_paths:
            value = value.replace(workspace_path, "verification-workspace")
        value = value.replace("/privateverification-workspace", "verification-workspace")
        value = re.sub(r"(?:/private)?/var/folders/[^\s\"<]+", "verification-workspace", value)
        return re.sub(
            r"verification-workspace/results/\d{4}-\d{2}-\d{2}",
            "verification-workspace/results/verification-run",
            value,
        )

    for cell in notebook.cells:
        cell.metadata.pop("execution", None)
        retained_outputs = []
        for output in cell.get("outputs", []):
            if output.get("output_type") == "stream" and output.get("name") == "stderr":
                continue
            if isinstance(output.get("text"), str):
                output["text"] = scrub(output["text"])
            data = output.get("data", {})
            for mime, value in list(data.items()):
                if isinstance(value, str):
                    data[mime] = scrub(value)
            if (
                retained_outputs
                and output.get("output_type") == "stream"
                and retained_outputs[-1].get("output_type") == "stream"
                and retained_outputs[-1].get("name") == output.get("name")
            ):
                retained_outputs[-1]["text"] = retained_outputs[-1].get("text", "") + output.get("text", "")
            else:
                retained_outputs.append(output)
        cell["outputs"] = retained_outputs
    notebook.metadata.pop("widgets", None)
    nbformat.write(notebook, path)


def materialize_reviewed_inputs(
    repository: Path,
    ref: str,
    relative_paths: tuple[str, ...],
    destination: Path,
) -> dict[str, str]:
    """Materialize and hash exact blobs from a pinned reviewed Git tree."""
    blob_map = {blob.path: blob for blob in repository_blobs(repository, ref)}
    missing = [relative for relative in relative_paths if relative not in blob_map]
    if missing:
        raise ReleaseAssetError(f"Reviewed verification inputs are missing from {ref}: {missing}")
    destination.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for relative in relative_paths:
        payload = read_git_blob(repository, blob_map[relative].object_id)
        expected_hash = hashlib.sha256(payload).hexdigest()
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(target, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if target.is_symlink() or not target.is_file() or sha256_file(target) != expected_hash:
            raise ReleaseAssetError(f"Materialized verification input failed hash validation: {relative}")
        hashes[relative] = expected_hash
    return hashes


def execute_verification_notebooks(repository: Path, output_dir: Path, ref: str = "HEAD") -> list[Path]:
    repository = repository.resolve()
    output_dir = _lexical_absolute(output_dir)
    _reject_symlink_components(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(output_dir)

    with tempfile.TemporaryDirectory(prefix="llm-lr-verification-") as temporary:
        workspace = Path(temporary)
        materialize_reviewed_inputs(repository, ref, VERIFICATION_INPUTS, workspace)
        staged_outputs = workspace / "executed-notebooks"
        staged_outputs.mkdir()

        guard_dir = workspace / "network-guard"
        guard_dir.mkdir()
        (guard_dir / "sitecustomize.py").write_text(_network_guard_source(), encoding="utf-8")
        kernel_prefix = workspace / "kernel"
        environment = os.environ.copy()
        environment.pop("OPENAI_API_KEY", None)
        environment["MPLBACKEND"] = "Agg"
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            str(guard_dir) if not existing_pythonpath else str(guard_dir) + os.pathsep + existing_pythonpath
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "ipykernel",
                "install",
                "--prefix",
                str(kernel_prefix),
                "--name",
                "llm-estimate-lrs-verification",
                "--display-name",
                "Python (llm-estimate-lrs verification)",
            ],
            cwd=workspace,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        jupyter_path = str(kernel_prefix / "share/jupyter")
        environment["JUPYTER_PATH"] = (
            jupyter_path
            if not environment.get("JUPYTER_PATH")
            else jupyter_path + os.pathsep + environment["JUPYTER_PATH"]
        )

        executed: list[Path] = []
        for notebook_name in NOTEBOOKS:
            source = workspace / notebook_name
            target_name = f"{source.stem}.executed.ipynb"
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "jupyter",
                    "nbconvert",
                    "--to",
                    "notebook",
                    "--execute",
                    "--ExecutePreprocessor.timeout=-1",
                    "--ExecutePreprocessor.kernel_name=llm-estimate-lrs-verification",
                    "--output",
                    target_name,
                    "--output-dir",
                    str(staged_outputs),
                    str(source),
                ],
                cwd=workspace,
                env=environment,
                check=True,
            )
            staged_target = staged_outputs / target_name
            _scrub_execution_metadata(staged_target, workspace)
            target = output_dir / target_name
            write_bytes_atomically(target, staged_target.read_bytes())
            executed.append(target)
    return executed


def write_asset_checksums(output_dir: Path, output: Path) -> Path:
    output_dir = output_dir.resolve()
    output = _lexical_absolute(output)
    _reject_symlink_components(output.parent)
    if output.is_symlink():
        raise ReleaseAssetError(f"Asset checksum output cannot be a symbolic link: {output}")
    assets: list[Path] = []
    for path in sorted(output_dir.rglob("*")):
        if path == output or path.name.endswith(".tmp"):
            continue
        if path.is_symlink():
            raise ReleaseAssetError(f"Release asset cannot be a symbolic link: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ReleaseAssetError(f"Release asset is not a regular file: {path}")
        assets.append(path)
    if not assets:
        raise ReleaseAssetError("No release assets were found for checksumming.")
    lines = [f"{sha256_file(path)}  {path.relative_to(output_dir).as_posix()}" for path in assets]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def asset_inventory(output_dir: Path, *, require_expected_paths: bool = False) -> dict[str, str]:
    """Return the exact relative-path/SHA-256 inventory for a complete asset directory."""
    output_dir = output_dir.resolve()
    inventory: dict[str, str] = {}
    for path in sorted(output_dir.rglob("*")):
        if path.is_symlink():
            raise ReleaseAssetError(f"Release asset inventory contains a symbolic link: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ReleaseAssetError(f"Release asset inventory contains a nonregular entry: {path}")
        inventory[path.relative_to(output_dir).as_posix()] = sha256_file(path)
    if not inventory:
        raise ReleaseAssetError("Release asset inventory is empty")
    if require_expected_paths and set(inventory) != EXPECTED_ASSET_PATHS:
        missing = sorted(EXPECTED_ASSET_PATHS - set(inventory))
        extra = sorted(set(inventory) - EXPECTED_ASSET_PATHS)
        raise ReleaseAssetError(f"Release asset path inventory differs: missing={missing}, extra={extra}")
    return inventory


def _repository_relative_contract(repository: Path, contract: Path) -> Path:
    candidate = contract if contract.is_absolute() else repository / contract
    try:
        return candidate.resolve().relative_to(repository.resolve())
    except ValueError as exc:
        raise ReleaseAssetError("Release contract must be inside the repository") from exc


def _validation_report(
    repository: Path,
    pinned_commit: str,
    mode: str,
    output: Path,
    *,
    contract: Path | None = None,
) -> Path:
    if contract is None:
        raise ReleaseAssetError("Release validation requires a versioned contract")
    relative_contract = _repository_relative_contract(repository, contract)
    validator = repository.resolve() / "scripts" / "validate_release.py"
    if validator.is_symlink() or not validator.is_file():
        raise ReleaseAssetError(f"Governance validator is not a regular file: {validator}")
    command = [
        sys.executable,
        str(validator),
        "--release",
        "--mode",
        mode,
        "--contract",
        relative_contract.as_posix(),
        "--ref",
        pinned_commit,
    ]
    result = subprocess.run(
        command,
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    rendered = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return write_bytes_atomically(output, rendered)


def build_release_assets(
    repository: Path,
    output_dir: Path,
    ref: str,
    mode: str,
    *,
    contract: Path | None = None,
) -> dict[str, Path]:
    repository = repository.resolve()
    unresolved_output = _lexical_absolute(output_dir)
    expected_unresolved = repository / "dist"
    _reject_symlink_components(unresolved_output)
    _reject_symlink_components(expected_unresolved)
    output_dir = unresolved_output.resolve()
    expected_output = expected_unresolved.resolve()
    if output_dir != expected_output:
        raise ReleaseAssetError(f"Release assets are restricted to {expected_output}")
    require_full_local_clone(repository)
    pinned_commit = require_clean_ref(repository, ref)
    require_complete_local_objects(repository, pinned_commit)
    if output_dir.exists():
        _reject_symlink_components(unresolved_output)
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    validation_report = _validation_report(
        repository,
        pinned_commit,
        mode,
        output_dir / "validation-report.json",
        contract=contract,
    )
    if require_clean_ref(repository, ref) != pinned_commit:
        raise ReleaseAssetError("Release ref or working tree changed during candidate validation")

    source_archive = build_archive(repository, output_dir / "llm-estimate-lrs-v1.0.0.zip", pinned_commit)
    reference_archive = build_reference_archive(
        repository,
        output_dir / "reference-tables-v1.0.0.zip",
        pinned_commit,
    )
    executed = execute_verification_notebooks(repository, output_dir / "notebooks", pinned_commit)
    # Revalidate after executable candidate work so contracted namespace state
    # cannot change unnoticed during asset construction.
    validation_report = _validation_report(
        repository,
        pinned_commit,
        mode,
        output_dir / "validation-report.json",
        contract=contract,
    )
    if require_clean_ref(repository, ref) != pinned_commit:
        raise ReleaseAssetError("Release ref or working tree changed during asset construction")
    pre_attestation = [source_archive, reference_archive, *executed, validation_report]
    attestation = generate_attestation(
        repository,
        ref,
        pre_attestation,
        output_dir / "release-attestation.json",
        asset_root=output_dir,
        expected_commit=pinned_commit,
    )
    asset_checksums = write_asset_checksums(output_dir, output_dir / "SHA256SUMS")
    asset_inventory(output_dir, require_expected_paths=True)
    if require_clean_ref(repository, ref) != pinned_commit:
        raise ReleaseAssetError("Release ref or working tree changed before asset construction completed")
    return {
        "source_archive": source_archive,
        "reference_archive": reference_archive,
        "validation_report": validation_report,
        "attestation": attestation,
        "asset_checksums": asset_checksums,
        **{f"executed_notebook_{index}": path for index, path in enumerate(executed, start=1)},
    }


def verify_release_asset_determinism(
    repository: Path,
    output_dir: Path,
    ref: str,
    mode: str,
    *,
    contract: Path | None = None,
) -> dict[str, Path]:
    """Build the complete asset set twice and require identical path/hash inventories."""
    first_assets = build_release_assets(repository, output_dir, ref, mode, contract=contract)
    first_inventory = asset_inventory(output_dir, require_expected_paths=True)
    second_assets = build_release_assets(repository, output_dir, ref, mode, contract=contract)
    second_inventory = asset_inventory(output_dir, require_expected_paths=True)
    if first_inventory != second_inventory:
        missing = sorted(first_inventory.keys() - second_inventory.keys())
        extra = sorted(second_inventory.keys() - first_inventory.keys())
        changed = sorted(
            path
            for path in first_inventory.keys() & second_inventory.keys()
            if first_inventory[path] != second_inventory[path]
        )
        raise ReleaseAssetError(
            "Two-build release asset determinism failed: "
            f"missing={missing}, extra={extra}, changed={changed}"
        )
    if set(first_assets) != set(second_assets):
        raise ReleaseAssetError("Two-build release asset return inventory changed between builds")
    return second_assets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--mode", choices=("prepare", "final"), default="prepare")
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument(
        "--verify-determinism",
        action="store_true",
        help="Build the complete asset set twice and compare exact path/hash inventories",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        builder = verify_release_asset_determinism if args.verify_determinism else build_release_assets
        assets = builder(
            args.repository,
            args.output_dir,
            args.ref,
            args.mode,
            contract=args.contract,
        )
    except (OSError, ValueError, ReleaseAssetError, subprocess.CalledProcessError) as exc:
        print(f"Release-asset build failed: {exc}", file=sys.stderr)
        return 1
    for name, path in sorted(assets.items()):
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
