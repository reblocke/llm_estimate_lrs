#!/usr/bin/env python3
"""Attest the resolved release ref and every pre-attestation release asset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

if __package__:
    from scripts.build_release_archive import write_bytes_atomically
    from scripts.git_safety import no_lazy_fetch_environment
    from scripts.validate_contracts import load_contract
else:
    from build_release_archive import write_bytes_atomically
    from git_safety import no_lazy_fetch_environment
    from validate_contracts import load_contract

REPOSITORY_URL = "https://github.com/reblocke/llm_estimate_lrs"


def git_blob_bytes(repository: Path, commit: str, relative_path: str) -> bytes:
    """Read an immutable file blob from the attested commit."""
    return subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=repository,
        check=True,
        capture_output=True,
        env=no_lazy_fetch_environment(),
    ).stdout


def git_output(repository: Path, *args: str) -> str:
    """Run a read-only Git command and return stripped standard output."""
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        env=no_lazy_fetch_environment(),
    ).stdout.strip()


def _asset_paths(assets: Path | Iterable[Path]) -> list[Path]:
    paths = [assets] if isinstance(assets, Path) else list(assets)
    if not paths:
        raise ValueError("At least one pre-attestation asset is required")
    return [Path(os.path.abspath(path)) for path in paths]


def _read_regular_asset(path: Path) -> tuple[str, int]:
    """Hash a regular asset through a no-follow descriptor with identity checks."""
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        if current.is_symlink():
            raise ValueError(f"Attested asset path contains a symbolic link: {current}")
    try:
        before = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError(f"Attested asset is missing: {path}") from exc
    if path.is_symlink() or not stat.S_ISREG(before.st_mode):
        raise ValueError(f"Attested asset is not a regular non-symlink file: {path}")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"Could not open attested asset without following links: {path}") from exc
    digest = hashlib.sha256()
    size = 0
    with os.fdopen(descriptor, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError(f"Attested asset changed before it could be read: {path}")
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    after = path.lstat()
    if not stat.S_ISREG(after.st_mode) or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
        raise ValueError(f"Attested asset changed while it was being read: {path}")
    return digest.hexdigest(), size


def _resolved_symbolic_ref(repository: Path, ref: str) -> str:
    resolved = git_output(repository, "rev-parse", "--symbolic-full-name", ref)
    return resolved or ref


def generate_attestation(
    repository: Path,
    ref: str,
    assets: Path | Iterable[Path],
    output: Path,
    *,
    contract: Mapping[str, Any],
    asset_root: Path | None = None,
    expected_commit: str | None = None,
) -> Path:
    """Write a deterministic attestation for all assets that precede it."""
    repository = repository.resolve()
    output = Path(os.path.abspath(output))
    asset_root = Path(os.path.abspath(asset_root or output.parent))
    paths = _asset_paths(assets)

    if output in paths:
        raise ValueError("The attestation cannot attest itself")

    records: list[dict[str, str | int]] = []
    for path in paths:
        try:
            relative = path.relative_to(asset_root).as_posix()
        except ValueError as exc:
            raise ValueError(f"Asset is outside the asset root: {path}") from exc
        asset_hash, asset_size = _read_regular_asset(path)
        records.append(
            {
                "path": relative,
                "sha256": asset_hash,
                "bytes": asset_size,
            }
        )
    records.sort(key=lambda record: str(record["path"]))

    commit = git_output(repository, "rev-parse", f"{ref}^{{commit}}")
    if expected_commit is not None and commit != expected_commit:
        raise ValueError(f"Release ref moved during asset construction: expected {expected_commit}, observed {commit}")
    contracted_commit = str(contract["audited_commit"])
    if commit != contracted_commit:
        raise ValueError(
            "Attested release candidate does not match the contract: "
            f"expected {contracted_commit}, observed {commit}"
        )
    release_version = str(contract["release_version"])
    release_ref = str(contract["release_ref"])
    if release_ref != f"v{release_version}":
        raise ValueError("Contract release_ref must be v followed by release_version")
    commit_date = git_output(repository, "show", "-s", "--format=%cI", commit)
    manifest_bytes = git_blob_bytes(repository, commit, "manifests/manuscript_run_v1.json")
    checksums_bytes = git_blob_bytes(repository, commit, "checksums/SHA256SUMS")
    payload = {
        "schema_version": 2,
        "release_version": release_version,
        "release_ref": release_ref,
        "release_date": str(
            contract.get("release_date", contract["article"]["published_date"])
        ),
        "requested_ref": ref,
        "resolved_ref": _resolved_symbolic_ref(repository, ref),
        "release_commit": commit,
        "release_commit_date": commit_date,
        "repository": REPOSITORY_URL,
        "article_doi": str(contract["article"]["doi"]),
        "assets": records,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "repository_checksums_sha256": hashlib.sha256(checksums_bytes).hexdigest(),
    }
    rendered = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return write_bytes_atomically(output, rendered)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument("--ref", required=True)
    parser.add_argument(
        "--asset",
        action="append",
        default=[],
        type=Path,
        help="Pre-attestation asset; repeat for each asset.",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        help="Backward-compatible alias for one --asset value.",
    )
    parser.add_argument("--asset-root", type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repository = args.repository.resolve()
    contract = load_contract(args.contract, repository)
    assets = [*args.asset]
    if args.archive is not None:
        assets.append(args.archive)
    output = generate_attestation(
        repository,
        args.ref,
        assets,
        args.output.resolve(),
        contract=contract,
        asset_root=args.asset_root.resolve() if args.asset_root else None,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
