#!/usr/bin/env python3
"""Build a deterministic ZIP archive from the reviewed repository tree."""

from __future__ import annotations

import argparse
import os
import stat
import subprocess
import tempfile
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class GitBlob:
    path: str
    object_id: str
    mode: str


def repository_blobs(repository: Path, ref: str = "HEAD") -> list[GitBlob]:
    """Return reviewed regular blobs from an immutable Git tree."""
    result = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "--full-tree", ref],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    blobs: list[GitBlob] = []
    for raw_entry in result.stdout.split(b"\0"):
        if not raw_entry:
            continue
        metadata, separator, raw_path = raw_entry.partition(b"\t")
        if not separator:
            raise ValueError("Unexpected git ls-tree output while constructing the source archive")
        fields = metadata.split()
        if len(fields) != 3:
            raise ValueError("Unexpected git tree metadata while constructing the source archive")
        mode, object_type, object_id = (field.decode("ascii") for field in fields)
        relative = raw_path.decode("utf-8")
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise ValueError(
                f"Tracked archive entry is not a regular file blob: {relative} "
                f"(mode={mode}, type={object_type})"
            )
        blobs.append(GitBlob(relative, object_id, mode))
    return sorted(blobs, key=lambda blob: blob.path)


def read_git_blob(repository: Path, object_id: str) -> bytes:
    result = subprocess.run(
        ["git", "cat-file", "blob", object_id],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    return result.stdout


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def _reject_parent_symlinks(path: Path) -> Path:
    """Return a lexical absolute path after rejecting existing symlinked parents."""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for component in absolute.parent.parts[1:]:
        current /= component
        if current.is_symlink():
            raise ValueError(f"Archive output parent contains a symbolic link: {current}")
    return absolute


def write_zip_atomically(
    output: Path,
    expected_members: Sequence[str],
    writer: Callable[[zipfile.ZipFile], None],
) -> Path:
    """Write and validate a ZIP through an exclusive regular file before atomic replacement."""
    output = _reject_parent_symlinks(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output = _reject_parent_symlinks(output)
    descriptor, raw_staging_path = tempfile.mkstemp(
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=output.parent,
    )
    staging_path = Path(raw_staging_path)
    created_identity: os.stat_result | None = None
    replaced = False
    succeeded = False
    descriptor_open = True
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "w+b") as handle:
            descriptor_open = False
            created_identity = os.fstat(handle.fileno())
            if not stat.S_ISREG(created_identity.st_mode):
                raise ValueError("Exclusive archive staging object is not a regular file")
            with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_STORED) as archive:
                writer(archive)
            handle.flush()
            os.fsync(handle.fileno())
            handle.seek(0)
            with zipfile.ZipFile(handle, "r") as archive:
                observed_members = archive.namelist()
            if observed_members != list(expected_members):
                raise ValueError(
                    "Archive member inventory differs from the reviewed inventory: "
                    f"expected={list(expected_members)}, observed={observed_members}"
                )

            staged_identity = staging_path.lstat()
            if not stat.S_ISREG(staged_identity.st_mode) or not _same_file(created_identity, staged_identity):
                raise ValueError("Archive staging path changed before atomic replacement")
            os.replace(staging_path, output)
            replaced = True
            final_identity = output.lstat()
            if not stat.S_ISREG(final_identity.st_mode) or not _same_file(created_identity, final_identity):
                raise ValueError("Final archive output is not the validated regular staging file")
        succeeded = True
        return output
    finally:
        if descriptor_open:
            os.close(descriptor)
        if staging_path.is_symlink() or staging_path.exists():
            try:
                staged_identity = staging_path.lstat()
            except FileNotFoundError:
                pass
            else:
                if created_identity is None or _same_file(created_identity, staged_identity):
                    staging_path.unlink()
        if replaced and not succeeded and created_identity is not None:
            try:
                final_identity = output.lstat()
            except FileNotFoundError:
                pass
            else:
                if _same_file(created_identity, final_identity):
                    output.unlink()


def write_bytes_atomically(output: Path, payload: bytes) -> Path:
    """Write bytes through an exclusive regular staging file and atomically replace the leaf."""
    output = _reject_parent_symlinks(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output = _reject_parent_symlinks(output)
    descriptor, raw_staging_path = tempfile.mkstemp(
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=output.parent,
    )
    staging_path = Path(raw_staging_path)
    created_identity: os.stat_result | None = None
    replaced = False
    succeeded = False
    descriptor_open = True
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor_open = False
            created_identity = os.fstat(handle.fileno())
            if not stat.S_ISREG(created_identity.st_mode):
                raise ValueError("Exclusive output staging object is not a regular file")
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            staged_identity = staging_path.lstat()
            if not stat.S_ISREG(staged_identity.st_mode) or not _same_file(created_identity, staged_identity):
                raise ValueError("Output staging path changed before atomic replacement")
            os.replace(staging_path, output)
            replaced = True
            final_identity = output.lstat()
            if not stat.S_ISREG(final_identity.st_mode) or not _same_file(created_identity, final_identity):
                raise ValueError("Final output is not the validated regular staging file")
        succeeded = True
        return output
    finally:
        if descriptor_open:
            os.close(descriptor)
        if staging_path.is_symlink() or staging_path.exists():
            try:
                staged_identity = staging_path.lstat()
            except FileNotFoundError:
                pass
            else:
                if created_identity is None or _same_file(created_identity, staged_identity):
                    staging_path.unlink()
        if replaced and not succeeded and created_identity is not None:
            try:
                final_identity = output.lstat()
            except FileNotFoundError:
                pass
            else:
                if _same_file(created_identity, final_identity):
                    output.unlink()


def build_archive(repository: Path, output: Path, ref: str = "HEAD") -> Path:
    blobs = repository_blobs(repository, ref)
    expected_members = [blob.path for blob in blobs]

    def write_members(archive: zipfile.ZipFile) -> None:
        for blob in blobs:
            info = zipfile.ZipInfo(blob.path, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_STORED
            permissions = 0o755 if blob.mode == "100755" else 0o644
            info.external_attr = (stat.S_IFREG | permissions) << 16
            archive.writestr(info, read_git_blob(repository, blob.object_id), compress_type=zipfile.ZIP_STORED)

    return write_zip_atomically(output, expected_members, write_members)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repository = args.repository.resolve()
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    if status.stdout:
        raise SystemExit("Refusing to archive a dirty working tree; commit and review the release tree first.")
    output = build_archive(repository, args.output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
