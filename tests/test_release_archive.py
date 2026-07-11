from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

from scripts.build_release_archive import build_archive, write_zip_atomically
from scripts.check_release_hygiene import scan_archive


def _initialize_repository(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "release@example.invalid"], cwd=path, check=True)


def test_release_archive_contains_only_reviewed_tree(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _initialize_repository(repository)
    (repository / "README.md").write_text("Reviewed source tree\n", encoding="utf-8")
    checksums = repository / "checksums" / "SHA256SUMS"
    checksums.parent.mkdir()
    checksums.write_text("reviewed inventory\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "Accepted-paper reproducibility release"], cwd=repository, check=True)
    archive_path = build_archive(repository, tmp_path / "release.zip")
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    tracked = {
        item
        for item in subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "-z", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
        ).stdout.decode("utf-8").split("\0")
        if item
    }
    assert names == tracked
    assert "README.md" in names
    assert scan_archive(archive_path) == []


def test_release_archive_rejects_tracked_symlink(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _initialize_repository(repository)
    outside = tmp_path / "private.txt"
    outside.write_text("must not be archived\n", encoding="utf-8")
    link = repository / "linked.txt"
    link.symlink_to(outside)
    subprocess.run(["git", "add", "linked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "Add source"], cwd=repository, check=True)

    try:
        build_archive(repository, tmp_path / "release.zip")
    except ValueError as exc:
        assert "not a regular file" in str(exc)
    else:
        raise AssertionError("tracked symlink was included in the release archive")


def test_release_archive_reads_head_blob_not_working_tree_symlink(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _initialize_repository(repository)
    tracked = repository / "public.txt"
    tracked.write_text("reviewed public bytes\n", encoding="utf-8")
    subprocess.run(["git", "add", "public.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "Add public source"], cwd=repository, check=True)

    outside = tmp_path / "private.txt"
    outside.write_text("private working-tree bytes\n", encoding="utf-8")
    tracked.unlink()
    tracked.symlink_to(outside)
    archive_path = build_archive(repository, tmp_path / "release.zip")

    with zipfile.ZipFile(archive_path) as archive:
        assert archive.read("public.txt") == b"reviewed public bytes\n"
        assert b"private working-tree bytes" not in archive.read("public.txt")


def test_release_archive_ignores_broken_legacy_temp_symlink_and_replaces_output_symlink(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _initialize_repository(repository)
    (repository / "README.md").write_text("Reviewed source tree\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "Add public source"], cwd=repository, check=True)

    output = tmp_path / "release.zip"
    outside_output = tmp_path / "outside-output.zip"
    output.symlink_to(outside_output)
    legacy_temp = output.with_suffix(output.suffix + ".tmp")
    outside_temp = tmp_path / "outside-temp.zip"
    legacy_temp.symlink_to(outside_temp)

    archive_path = build_archive(repository, output)

    assert archive_path == output
    assert output.is_file() and not output.is_symlink()
    assert legacy_temp.is_symlink()
    assert not outside_output.exists()
    assert not outside_temp.exists()
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []


def test_atomic_zip_cleans_staging_file_and_preserves_output_on_error(tmp_path: Path) -> None:
    output = tmp_path / "release.zip"
    output.write_bytes(b"existing output\n")

    def fail_after_write(archive: zipfile.ZipFile) -> None:
        archive.writestr("file.txt", b"partial")
        raise RuntimeError("injected writer failure")

    try:
        write_zip_atomically(output, ["file.txt"], fail_after_write)
    except RuntimeError as exc:
        assert "injected writer failure" in str(exc)
    else:
        raise AssertionError("injected ZIP writer failure was ignored")

    assert output.read_bytes() == b"existing output\n"
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []
