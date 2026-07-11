from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.build_checksums import build_checksums
from scripts.verify_checksums import verify_checksums


def test_checksum_builder_uses_sorted_tracked_tree_and_excludes_itself(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "z.txt").write_text("z\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    checksum = tmp_path / "checksums" / "SHA256SUMS"
    checksum.parent.mkdir()
    checksum.write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)

    build_checksums(tmp_path, checksum)
    paths = [line.split("  ", 1)[1] for line in checksum.read_text(encoding="utf-8").splitlines()]
    assert paths == ["a.txt", "z.txt"]
    assert verify_checksums(checksum, tmp_path) == 2


def test_checksum_builder_refuses_missing_tracked_file(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("value\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    tracked.unlink()

    try:
        build_checksums(tmp_path, tmp_path / "SHA256SUMS")
    except FileNotFoundError as exc:
        assert "tracked.txt" in str(exc)
    else:
        raise AssertionError("missing tracked file was accepted")
