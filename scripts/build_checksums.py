#!/usr/bin/env python3
"""Build a sorted SHA-256 inventory for every reviewed tracked release file."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tracked_files(root: Path, output: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    output = output.resolve()
    files = sorted(
        root / item.decode("utf-8")
        for item in result.stdout.split(b"\0")
        if item and (root / item.decode("utf-8")).resolve() != output
    )
    missing = [path.relative_to(root).as_posix() for path in files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Tracked release files are missing from the working tree: {missing}")
    return files


def build_checksums(root: Path, output: Path) -> Path:
    root = root.resolve()
    output = output.resolve()
    files = tracked_files(root, output)
    if not files:
        raise ValueError("No tracked release files were found")
    lines = [f"{sha256_file(path)}  {path.relative_to(root).as_posix()}" for path in files]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("checksums/SHA256SUMS"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        output = build_checksums(args.root, args.output)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"Checksum generation failed: {exc}")
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
