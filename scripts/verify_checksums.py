#!/usr/bin/env python3
"""Verify a sorted SHA-256 checksum manifest without modifying files."""

from __future__ import annotations

import argparse
import hashlib
import re
import stat
import subprocess
from pathlib import Path

CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64}) [ *](.+)$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tracked_regular_files(root: Path, checksum_file: Path) -> list[str]:
    """Return the exact regular-file inventory recorded by the Git index."""
    try:
        checksum_relative = checksum_file.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("Checksum manifest must be inside the repository root") from exc
    result = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ValueError(f"Could not inspect tracked release files: {result.stderr.decode(errors='replace').strip()}")

    tracked: list[str] = []
    for raw_entry in result.stdout.split(b"\0"):
        if not raw_entry:
            continue
        metadata, separator, raw_path = raw_entry.partition(b"\t")
        if not separator:
            raise ValueError("Unexpected git ls-files output while verifying checksums")
        fields = metadata.split()
        if len(fields) != 3:
            raise ValueError("Unexpected git index metadata while verifying checksums")
        mode, _object_id, stage = (field.decode("ascii") for field in fields)
        relative = raw_path.decode("utf-8")
        if relative == checksum_relative:
            continue
        if stage != "0" or mode not in {"100644", "100755"}:
            raise ValueError(f"Tracked release entry is not a regular file: {relative} (mode={mode}, stage={stage})")
        path = root / relative
        try:
            observed_mode = path.lstat().st_mode
        except FileNotFoundError as exc:
            raise ValueError(f"Tracked release file is missing: {relative}") from exc
        if path.is_symlink() or not stat.S_ISREG(observed_mode):
            raise ValueError(f"Tracked release entry is not a regular working-tree file: {relative}")
        tracked.append(relative)
    return sorted(tracked)


def verify_checksums(checksum_file: Path, root: Path) -> int:
    """Verify all checksum entries and return the number checked."""
    checksum_file = checksum_file.resolve()
    root = root.resolve()
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(checksum_file.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line:
            continue
        match = CHECKSUM_LINE.fullmatch(raw_line)
        if match is None:
            raise ValueError(f"Invalid checksum line {line_number}: {raw_line!r}")
        expected, relative_text = match.groups()
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Unsafe checksum path on line {line_number}: {relative_text!r}")
        normalized = relative.as_posix()
        if normalized in seen:
            raise ValueError(f"Duplicate checksum path: {normalized}")
        seen.add(normalized)
        entries.append((expected, normalized))

    paths = [path for _, path in entries]
    if paths != sorted(paths):
        raise ValueError("Checksum entries must be sorted lexicographically by path")
    if not entries:
        raise ValueError("Checksum manifest contains no entries")

    tracked = tracked_regular_files(root, checksum_file)
    if paths != tracked:
        missing = sorted(set(tracked) - set(paths))
        extra = sorted(set(paths) - set(tracked))
        raise ValueError(
            "Checksum inventory differs from the tracked release tree: "
            f"missing={missing}, extra={extra}"
        )

    failures = []
    for expected, relative_text in entries:
        path = root / relative_text
        if path.is_symlink() or not path.is_file():
            failures.append(f"missing: {relative_text}")
            continue
        observed = sha256_file(path)
        if observed != expected:
            failures.append(f"mismatch: {relative_text} (expected {expected}, got {observed})")
    if failures:
        raise ValueError("Checksum verification failed:\n" + "\n".join(failures))
    return len(entries)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checksum_file", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        count = verify_checksums(args.checksum_file, args.root)
    except (OSError, ValueError) as exc:
        print(exc)
        return 1
    print(f"Verified {count} SHA-256 entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
