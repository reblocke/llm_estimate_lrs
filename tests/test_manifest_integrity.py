from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import jsonschema
import pytest

from scripts.build_manifest import build_manifest
from scripts.verify_checksums import verify_checksums

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_manifest_schema_and_artifact_hashes() -> None:
    manifest_path = ROOT / "manifests/manuscript_run_v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "manifests/manifest.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(manifest, schema)
    assert manifest["release_version"] == "1.0.0"
    assert manifest["release_ref"] == "v1.0.0"
    assert manifest["article"]["published_date"] == "2026-07-11"
    assert manifest["article"]["publication_status"] == "published_unedited_early_access"
    assert manifest["article"]["publisher_url"] == "https://doi.org/10.1038/s41598-026-61766-2"
    unresolved_marker = "TO_BE" + "_FILLED"
    assert unresolved_marker not in manifest_path.read_text(encoding="utf-8")
    assert manifest["environment"]["lockfile_sha256"] == sha256(ROOT / "uv.lock")

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
        path = ROOT / artifact["path"]
        assert path.is_file(), artifact["path"]
        assert artifact["byte_size"] == path.stat().st_size
        assert artifact["sha256"] == sha256(path)


def test_manifest_builder_is_deterministic(tmp_path: Path) -> None:
    generated = build_manifest(ROOT, tmp_path / "manifest.json")
    assert generated.read_bytes() == (ROOT / "manifests/manuscript_run_v1.json").read_bytes()


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
