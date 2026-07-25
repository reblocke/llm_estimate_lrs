from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import jsonschema
import pytest

from scripts.git_safety import no_lazy_fetch_environment, require_complete_local_objects
from scripts.verify_checksums import verify_checksums

ROOT = Path(__file__).resolve().parents[1]
V1_REF = "v1.0.0"


@pytest.fixture(scope="module", autouse=True)
def require_local_v1_object_closure() -> None:
    require_complete_local_objects(ROOT, V1_REF)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob(relative_path: str, ref: str = V1_REF) -> bytes:
    return subprocess.run(
        ["git", "show", f"{ref}:{relative_path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        env=no_lazy_fetch_environment(),
    ).stdout


def git_archive(output: Path, ref: str = V1_REF) -> None:
    subprocess.run(
        ["git", "archive", "--format=zip", "--output", str(output), ref],
        cwd=ROOT,
        check=True,
        env=no_lazy_fetch_environment(),
    )


def test_historical_git_helpers_disable_lazy_fetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, str]] = []

    def record_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        calls.append(environment)
        return subprocess.CompletedProcess(command, 0, stdout=b"historical blob")

    monkeypatch.setattr(subprocess, "run", record_run)

    assert git_blob("historical.txt") == b"historical blob"
    git_archive(tmp_path / "historical.zip")
    assert len(calls) == 2
    assert all(environment["GIT_NO_LAZY_FETCH"] == "1" for environment in calls)


def test_manifest_schema_and_artifact_hashes() -> None:
    manifest_path = ROOT / "manifests/manuscript_run_v1.json"
    schema_path = ROOT / "manifests/manifest.schema.json"
    manifest_bytes = git_blob("manifests/manuscript_run_v1.json")
    schema_bytes = git_blob("manifests/manifest.schema.json")
    assert manifest_path.read_bytes() == manifest_bytes
    assert schema_path.read_bytes() == schema_bytes

    manifest = json.loads(manifest_bytes)
    schema = json.loads(schema_bytes)
    jsonschema.validate(manifest, schema)
    assert manifest["release_version"] == "1.0.0"
    assert manifest["release_ref"] == "v1.0.0"
    assert manifest["article"]["published_date"] == "2026-07-11"
    assert manifest["article"]["publication_status"] == "published_unedited_early_access"
    assert manifest["article"]["publisher_url"] == "https://doi.org/10.1038/s41598-026-61766-2"
    unresolved_marker = "TO_BE" + "_FILLED"
    assert unresolved_marker not in manifest_bytes.decode("utf-8")
    assert manifest["environment"]["lockfile_sha256"] == hashlib.sha256(git_blob("uv.lock")).hexdigest()

    artifacts = [
        *manifest["configurations"],
        *manifest["prompts"],
        *manifest["inputs"],
        *manifest["outputs"],
        *manifest["code"],
    ]
    paths = [artifact["path"] for artifact in artifacts]
    assert len(paths) == len(set(paths))
    for artifact in artifacts:
        payload = git_blob(artifact["path"])
        assert artifact["byte_size"] == len(payload)
        assert artifact["sha256"] == hashlib.sha256(payload).hexdigest()


def test_manifest_builder_is_deterministic(tmp_path: Path) -> None:
    archive = tmp_path / "v1.zip"
    snapshot = tmp_path / "v1"
    git_archive(archive)
    with zipfile.ZipFile(archive) as release:
        release.extractall(snapshot)
    generated = tmp_path / "manifest.json"
    subprocess.run(
        [
            sys.executable,
            str(snapshot / "scripts/build_manifest.py"),
            "--root",
            str(snapshot),
            "--output",
            str(generated),
        ],
        cwd=snapshot,
        check=True,
    )
    assert generated.read_bytes() == git_blob("manifests/manuscript_run_v1.json")


def test_checksum_verifier_accepts_sorted_manifest_and_rejects_changes(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("alpha\n", encoding="utf-8")
    second.write_text("beta\n", encoding="utf-8")
    checksum_file = tmp_path / "SHA256SUMS"
    checksum_file.write_text(
        f"{sha256(first)}  a.txt\n{sha256(second)}  b.txt\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "a.txt", "b.txt"], cwd=tmp_path, check=True)
    assert verify_checksums(checksum_file, tmp_path) == 2
    second.write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mismatch"):
        verify_checksums(checksum_file, tmp_path)


def test_checksum_verifier_rejects_incomplete_inventory(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    first = tmp_path / "a.txt"
    omitted = tmp_path / "omitted.txt"
    first.write_text("alpha\n", encoding="utf-8")
    omitted.write_text("must be covered\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt", "omitted.txt"], cwd=tmp_path, check=True)
    checksum_file = tmp_path / "SHA256SUMS"
    checksum_file.write_text(f"{sha256(first)}  a.txt\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"missing=\['omitted.txt'\]"):
        verify_checksums(checksum_file, tmp_path)
