#!/usr/bin/env python3
"""Validate frozen data and release metadata without network or API access."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import jsonschema
import numpy as np
import pandas as pd
import yaml

if __package__:
    from scripts.git_safety import (
        no_lazy_fetch_environment,
        require_complete_local_objects,
        require_full_local_clone,
    )
    from scripts.validate_contracts import (
        ContractValidationError,
        validate_history_policy,
        validate_release_contract,
    )
    from scripts.validate_metadata import (
        STAGE2_REQUIRED_PATHS,
        MetadataValidationError,
        validate_metadata_contracts,
    )
    from scripts.verify_checksums import verify_checksums
else:
    from git_safety import (
        no_lazy_fetch_environment,
        require_complete_local_objects,
        require_full_local_clone,
    )
    from validate_contracts import (
        ContractValidationError,
        validate_history_policy,
        validate_release_contract,
    )
    from validate_metadata import (
        STAGE2_REQUIRED_PATHS,
        MetadataValidationError,
        validate_metadata_contracts,
    )
    from verify_checksums import verify_checksums

ROOT = Path(__file__).resolve().parents[1]
FROZEN_V1_ARTICLE_TITLE = (
    "Large language models generate diagnostic likelihood ratios with low mean bias but wide dispersion"
)
FROZEN_V1_ARTICLE_DOI = "10.1038/s41598-026-61766-2"
FROZEN_V1_RELEASE_VERSION = "1.0.0"
FROZEN_V1_RELEASE_REF = "v1.0.0"
FROZEN_V1_RELEASE_COMMIT = "a6824fc712e6d5c7c58edde495c239629356ae35"
FROZEN_V1_RELEASE_TAG_MESSAGE = "Accepted-paper reproducibility release"
FROZEN_V1_LEGACY_MERGE_BASE = "9ab48f0244daff1b7c9ed58f2f4fca2572284f65"
FROZEN_V1_RELEASE_BRANCH = "release/accepted-paper-reproducibility-v1"
FROZEN_V1_PUBLISHER_URL = "https://doi.org/10.1038/s41598-026-61766-2"
FROZEN_V1_PUBLISHED_DATE = "2026-07-11"

WORKBOOK_HASHES = {
    "NNT_LRs_08-26-2025.xlsx": "644f0558328a8f04f460a5ebfa2fc04e6d3571f655d084ea076488c7ba17da89",
    "nnt_lrs_with_estimated.xlsx": "c375229a27f0854957f6b8963ece145e94d00e4fa75e7e2756e5d130f6f7110d",
}

MODEL_COLUMNS = (
    "lr_gpt-4o-2024-11-20",
    "lr_o3-2025-04-16",
    "lr_gpt-5",
)

MODEL_IDS = (
    "gpt-4o-2024-11-20",
    "o3-2025-04-16",
    "gpt-5",
)

CATEGORY_COUNTS = {
    "Strong Negative": 17,
    "Moderate Negative": 22,
    "Weak Negative": 60,
    "Negligible": 400,
    "Weak Positive": 120,
    "Moderate Positive": 52,
    "Strong Positive": 29,
}

FEATURE_COUNTS = {
    "is_sign_or_symptom": 416,
    "is_history": 134,
    "is_test_result": 110,
    "is_imaging": 57,
    "is_diagnostic_adjudication": 8,
}

NOTEBOOKS = (
    "data_analysis.ipynb",
    "supplementary_analyses.ipynb",
    "lr_scraper_estimator.ipynb",
    "threshold_perturbation_sensitivity_analysis.ipynb",
)


class ReleaseValidationError(RuntimeError):
    """Raised when a release invariant does not hold."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseValidationError(message)


def git(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        env=no_lazy_fetch_environment(),
    )


def git_bytes(repository: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=False,
        capture_output=True,
        env=no_lazy_fetch_environment(),
    )


@dataclass(frozen=True)
class CandidateSnapshot:
    """An immutable candidate commit materialized from raw Git objects."""

    requested_ref: str
    commit: str
    tree: str
    root: Path


@dataclass(frozen=True)
class GitTreeEntry:
    """One path and blob recorded in a candidate Git tree."""

    mode: str
    object_type: str
    object_id: str
    relative_path: str


def _resolve_candidate(repository: Path, candidate_ref: str) -> tuple[str, str]:
    require(bool(candidate_ref), "Candidate ref must not be empty")
    require(candidate_ref == candidate_ref.strip(), "Candidate ref must not contain surrounding whitespace")
    require(
        not candidate_ref.startswith("-") and not any(ord(character) < 32 for character in candidate_ref),
        "Candidate ref contains unsafe characters",
    )
    resolved: dict[str, str] = {}
    for object_type in ("commit", "tree"):
        result = git(
            repository,
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{candidate_ref}^{{{object_type}}}",
        )
        require(
            result.returncode == 0,
            f"Could not resolve candidate {object_type} for {candidate_ref}: {result.stderr.strip()}",
        )
        object_id = result.stdout.strip()
        require(
            len(object_id) == 40 and all(character in "0123456789abcdef" for character in object_id),
            f"Candidate {object_type} did not resolve to a full object ID: {candidate_ref}",
        )
        resolved[object_type] = object_id
    return resolved["commit"], resolved["tree"]


def _safe_tree_path(raw_path: bytes) -> str:
    try:
        relative_path = raw_path.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ReleaseValidationError("Candidate tree contains a non-UTF-8 path") from exc
    path = PurePosixPath(relative_path)
    require(
        bool(relative_path)
        and "\\" not in relative_path
        and not path.is_absolute()
        and str(path) == relative_path
        and all(part not in {"", ".", ".."} for part in path.parts),
        f"Candidate tree contains an unsafe path: {relative_path!r}",
    )
    require(
        all(part.casefold() != ".git" for part in path.parts),
        f"Candidate tree contains a reserved Git path: {relative_path}",
    )
    return relative_path


def _candidate_tree_entries(repository: Path, tree: str) -> list[GitTreeEntry]:
    result = git_bytes(repository, "ls-tree", "-r", "-z", "--full-tree", tree)
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    require(result.returncode == 0, f"Could not inspect candidate tree {tree}: {stderr}")

    entries: list[GitTreeEntry] = []
    seen_paths: set[str] = set()
    for raw_entry in result.stdout.split(b"\0"):
        if not raw_entry:
            continue
        metadata, separator, raw_path = raw_entry.partition(b"\t")
        require(bool(separator), "Unexpected Git tree output during candidate materialization")
        fields = metadata.split()
        require(len(fields) == 3, "Unexpected Git tree metadata during candidate materialization")
        try:
            mode, object_type, object_id = (
                field.decode("ascii", errors="strict") for field in fields
            )
        except UnicodeDecodeError as exc:
            raise ReleaseValidationError(
                "Candidate tree contains non-ASCII Git metadata"
            ) from exc
        relative_path = _safe_tree_path(raw_path)
        require(
            relative_path not in seen_paths,
            f"Candidate tree contains a duplicate path: {relative_path}",
        )
        require(
            len(object_id) == 40
            and all(character in "0123456789abcdef" for character in object_id),
            f"Candidate tree contains an invalid object ID for {relative_path}",
        )
        entries.append(
            GitTreeEntry(
                mode=mode,
                object_type=object_type,
                object_id=object_id,
                relative_path=relative_path,
            )
        )
        seen_paths.add(relative_path)
    return entries


def _require_regular_tree_entry(entry: GitTreeEntry) -> None:
    require(
        entry.object_type == "blob" and entry.mode in {"100644", "100755"},
        "Tracked release entry is not a regular file: "
        f"{entry.relative_path} (mode={entry.mode}, type={entry.object_type})",
    )


def _materialize_candidate_tree(repository: Path, tree: str, destination: Path) -> None:
    """Write exact candidate blobs without invoking checkout hooks or filters."""

    destination.mkdir()
    for entry in _candidate_tree_entries(repository, tree):
        _require_regular_tree_entry(entry)
        output_path = destination / PurePosixPath(entry.relative_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        blob = git_bytes(repository, "cat-file", "blob", entry.object_id)
        stderr = blob.stderr.decode("utf-8", errors="replace").strip()
        require(
            blob.returncode == 0,
            f"Could not read candidate blob for {entry.relative_path}: {stderr}",
        )
        try:
            with output_path.open("xb") as handle:
                handle.write(blob.stdout)
            output_path.chmod(0o755 if entry.mode == "100755" else 0o644)
        except OSError as exc:
            raise ReleaseValidationError(
                f"Could not materialize candidate file: {entry.relative_path}"
            ) from exc


@contextmanager
def materialized_candidate(
    repository: Path = ROOT,
    candidate_ref: str = "HEAD",
) -> Iterator[CandidateSnapshot]:
    """Materialize a pinned candidate and fail if the caller's ref moves."""

    try:
        require_full_local_clone(repository)
    except ValueError as exc:
        raise ReleaseValidationError(str(exc)) from exc
    initial_commit, initial_tree = _resolve_candidate(repository, candidate_ref)
    try:
        require_complete_local_objects(repository, initial_commit)
    except ValueError as exc:
        raise ReleaseValidationError(str(exc)) from exc

    with tempfile.TemporaryDirectory(prefix="release-candidate-") as temporary_parent:
        candidate_root = Path(temporary_parent) / "candidate"
        ref_error: ReleaseValidationError | None = None
        try:
            _materialize_candidate_tree(repository, initial_tree, candidate_root)
            yield CandidateSnapshot(
                requested_ref=candidate_ref,
                commit=initial_commit,
                tree=initial_tree,
                root=candidate_root,
            )
        finally:
            try:
                final_commit, final_tree = _resolve_candidate(repository, candidate_ref)
                if (final_commit, final_tree) != (initial_commit, initial_tree):
                    ref_error = ReleaseValidationError(
                        f"Candidate ref moved during validation: {candidate_ref} "
                        f"({initial_commit}/{initial_tree} -> {final_commit}/{final_tree})"
                    )
            except ReleaseValidationError as exc:
                ref_error = ReleaseValidationError(
                    f"Candidate ref became unresolved during validation: {candidate_ref}"
                )
                ref_error.add_note(str(exc))

            if ref_error is not None:
                raise ref_error


def boolean_sum(series: pd.Series) -> int:
    if pd.api.types.is_bool_dtype(series):
        return int(series.sum())
    normalized = series.astype(str).str.strip().str.lower()
    require(normalized.isin({"true", "false", "1", "0"}).all(), f"Invalid Boolean values in {series.name}")
    return int(normalized.isin({"true", "1"}).sum())


def validate_source_workbooks(root: Path = ROOT) -> dict[str, str]:
    observed: dict[str, str] = {}
    for relative_path, expected_hash in WORKBOOK_HASHES.items():
        path = root / relative_path
        require(path.is_file(), f"Missing source workbook: {relative_path}")
        observed_hash = sha256(path)
        require(observed_hash == expected_hash, f"Source workbook hash changed: {relative_path}")
        observed[relative_path] = observed_hash
    return observed


def validate_canonical_dataset(root: Path = ROOT) -> dict[str, object]:
    canonical_path = root / "data/curated/diagnostic_lrs_manuscript_v1.csv"
    require(canonical_path.is_file(), f"Missing canonical dataset: {canonical_path.relative_to(root)}")
    frame = pd.read_csv(canonical_path)
    require(len(frame) == 700, f"Canonical dataset must have 700 rows, found {len(frame)}")

    expected_ids = [f"lr_{index:04d}" for index in range(1, 701)]
    require(frame["row_id"].tolist() == expected_ids, "Canonical row IDs or row order changed")
    require(frame["row_id"].is_unique, "Canonical row IDs are not unique")

    condition_column = "condition_full" if "condition_full" in frame else "condition_raw"
    condition_count = int(frame[condition_column].nunique(dropna=True))
    require(condition_count == 30, f"Expected 30 conditions, found {condition_count}")

    numeric_columns = ("lr_reported", *MODEL_COLUMNS)
    for column in numeric_columns:
        require(column in frame, f"Canonical dataset is missing {column}")
        values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)
        require(np.isfinite(values).all(), f"{column} contains missing or non-finite values")
        require((values > 0).all(), f"{column} contains non-positive values")

    category_counts = frame["reported_qualitative_band"].value_counts().to_dict()
    require(category_counts == CATEGORY_COUNTS, f"LR category counts changed: {category_counts}")

    feature_counts = {column: boolean_sum(frame[column]) for column in FEATURE_COUNTS}
    require(feature_counts == FEATURE_COUNTS, f"Feature memberships changed: {feature_counts}")

    output_path = root / "data/model_outputs/manuscript_model_outputs_v1.csv"
    outputs = pd.read_csv(output_path)
    require(len(outputs) == 700, f"Manuscript model output table must have 700 rows, found {len(outputs)}")
    require(outputs["row_id"].tolist() == expected_ids, "Model output row IDs or order changed")
    for column in MODEL_COLUMNS:
        left = pd.to_numeric(frame[column], errors="raise").to_numpy(dtype=float)
        right = pd.to_numeric(outputs[column], errors="raise").to_numpy(dtype=float)
        require(np.array_equal(left, right), f"Frozen model outputs differ in {column}")

    crosswalk = pd.read_csv(root / "data/provenance/source_crosswalk_v1.csv")
    require(len(crosswalk) == 700, f"Source crosswalk must have 700 rows, found {len(crosswalk)}")
    require(crosswalk["row_id"].tolist() == expected_ids, "Source crosswalk row IDs or order changed")

    return {
        "rows": len(frame),
        "conditions": condition_count,
        "model_values": len(frame) * len(MODEL_COLUMNS),
        "category_counts": category_counts,
        "feature_counts": feature_counts,
    }


def validate_threshold_artifacts(root: Path = ROOT) -> dict[str, int]:
    base = root / "data/model_outputs/threshold_perturbation_v1"
    expected_rows = {
        "threshold_perturbation_cases.csv": 15,
        "threshold_perturbation_raw.csv": 15,
        "threshold_perturbation_summary.csv": 5,
        "threshold_perturbation_reviewer_table.csv": 5,
    }
    observed: dict[str, int] = {}
    for filename, row_count in expected_rows.items():
        path = base / filename
        require(path.is_file(), f"Missing frozen threshold artifact: {path.relative_to(root)}")
        frame = pd.read_csv(path)
        require(len(frame) == row_count, f"{filename} must have {row_count} rows, found {len(frame)}")
        observed[filename] = len(frame)

    raw = pd.read_csv(base / "threshold_perturbation_raw.csv")
    estimates = pd.to_numeric(raw["lr_estimate"], errors="coerce").to_numpy(dtype=float)
    require(np.isfinite(estimates).all() and (estimates > 0).all(), "Threshold estimates must be positive and finite")
    require((raw["error_status"].astype(str).str.lower() == "ok").all(), "Accepted threshold run contains failed calls")
    return observed


def validate_configs_and_prompts(root: Path = ROOT) -> dict[str, object]:
    models = json.loads((root / "config/manuscript_models_v1.json").read_text(encoding="utf-8"))
    configured_models = tuple(item["api_model"] for item in models["manuscript_models"])
    require(configured_models == MODEL_IDS, f"Manuscript model scope changed: {configured_models}")

    main_prompt = json.loads((root / "prompts/main_estimator_v1.json").read_text(encoding="utf-8"))
    threshold_prompt = json.loads((root / "prompts/threshold_perturbation_v1.json").read_text(encoding="utf-8"))
    require(len(main_prompt["few_shot_sets"]["rich_8"]) == 8, "Main rich few-shot set must contain eight examples")
    require(len(main_prompt["few_shot_sets"]["minimal_2"]) == 2, "Main minimal few-shot set must contain two examples")
    require(len(threshold_prompt["few_shot_set"]) == 2, "Threshold few-shot set must contain two examples")
    require(
        main_prompt["system_messages"] != threshold_prompt["system_messages"],
        "Distinct historical prompts were collapsed",
    )
    return {
        "models": configured_models,
        "main_prompt": main_prompt["prompt_id"],
        "threshold_prompt": threshold_prompt["prompt_id"],
    }


def validate_notebooks(root: Path = ROOT) -> None:
    for relative_path in NOTEBOOKS:
        path = root / relative_path
        require(path.is_file(), f"Missing notebook: {relative_path}")
        notebook = json.loads(path.read_text(encoding="utf-8"))
        for index, cell in enumerate(notebook.get("cells", [])):
            if cell.get("cell_type") != "code":
                continue
            require(cell.get("execution_count") is None, f"Stored execution count in {relative_path} cell {index}")
            require(cell.get("outputs", []) == [], f"Stored output in {relative_path} cell {index}")


def validate_manifest(root: Path = ROOT) -> dict[str, object]:
    manifest = json.loads((root / "manifests/manuscript_run_v1.json").read_text(encoding="utf-8"))
    schema = json.loads((root / "manifests/manifest.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(manifest, schema)
    require(
        manifest["release_version"] == FROZEN_V1_RELEASE_VERSION,
        "Frozen v1 manifest release version is inconsistent",
    )
    require(
        manifest["release_ref"] == FROZEN_V1_RELEASE_REF,
        "Frozen v1 manifest release ref is inconsistent",
    )
    require(
        manifest["article"]["doi"] == FROZEN_V1_ARTICLE_DOI,
        "Frozen v1 manifest article DOI is inconsistent",
    )
    require(
        manifest["article"]["published_date"] == FROZEN_V1_PUBLISHED_DATE,
        "Frozen v1 manifest publication date is inconsistent",
    )
    require(
        manifest["article"]["publication_status"] == "published_unedited_early_access",
        "Manifest article publication status is inconsistent",
    )
    require(
        manifest["article"]["publisher_url"] == FROZEN_V1_PUBLISHER_URL,
        "Frozen v1 manifest publisher URL is inconsistent",
    )
    return manifest


def validate_documentation(
    mode: Literal["prepare", "final"],
    contract: Mapping[str, Any],
    root: Path = ROOT,
) -> None:
    release_version = contract["release_version"]
    release_ref = contract["release_ref"]
    article = contract["article"]
    release_notes_path = f"RELEASE_NOTES_v{release_version}.md"
    cff = yaml.safe_load((root / "CITATION.cff").read_text(encoding="utf-8"))
    require(str(cff["version"]) == release_version, "CITATION.cff version is inconsistent with the release contract")
    require(cff["preferred-citation"]["doi"] == article["doi"], "CITATION.cff article DOI is inconsistent")
    require(cff["preferred-citation"]["title"] == article["title"], "CITATION.cff article title is inconsistent")
    require(
        str(cff["preferred-citation"]["date-published"]) == article["published_date"],
        "CITATION.cff article publication date is inconsistent",
    )
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    require(
        pyproject["project"]["urls"]["Homepage"] == article["publisher_url"],
        "Package homepage must match the contracted publisher URL",
    )

    required_text_paths = (
        "README.md",
        release_notes_path,
        "llms.txt",
        "docs/REPRODUCIBILITY.md",
    )
    for relative_path in required_text_paths:
        text = (root / relative_path).read_text(encoding="utf-8")
        require(article["doi"] in text, f"Article DOI missing from {relative_path}")

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    require(mode in {"prepare", "final"}, f"Unsupported release validation mode: {mode}")
    require("date-released" in cff, "Release candidate CITATION.cff requires date-released")
    release_date = str(cff["date-released"])
    if "release_date" in contract:
        require(
            contract["release_date"] == release_date,
            "Release contract date must match CITATION.cff date-released",
        )
    else:
        require(
            release_ref == FROZEN_V1_RELEASE_REF,
            "Successor release contract must record release_date",
        )
    require(
        f"## [{release_version}] - {release_date}" in changelog,
        "Release candidate changelog date must match CITATION.cff date-released",
    )
    require(
        f"## [{release_version}] - Unreleased" not in changelog,
        f"Release candidate changelog still marks {release_version} as Unreleased",
    )
    pending_phrases = (
        "until the tag is published",
        "prepared release identifier",
        "describe a prepared release",
        f"do not assert that the `{release_ref}` tag",
    )
    for relative_path in ("README.md", "llms.txt", release_notes_path):
        normalized = (root / relative_path).read_text(encoding="utf-8").casefold()
        require(
            not any(phrase in normalized for phrase in pending_phrases),
            f"Release candidate metadata remains pending in {relative_path}",
        )


def _require_regular_materialized_path(root: Path, relative_path: str) -> None:
    parts = PurePosixPath(relative_path).parts
    current = root
    for index, part in enumerate(parts):
        current /= part
        try:
            observed_mode = current.lstat().st_mode
        except FileNotFoundError as exc:
            raise ReleaseValidationError(
                f"Tracked release path is missing: {relative_path}"
            ) from exc
        if index < len(parts) - 1:
            require(
                not current.is_symlink() and stat.S_ISDIR(observed_mode),
                f"Tracked release path has a non-directory ancestor: {current.relative_to(root)}",
            )
        else:
            require(
                not current.is_symlink() and stat.S_ISREG(observed_mode),
                f"Tracked release entry is not a regular materialized file: {relative_path}",
            )


def validate_tracked_file_types(
    repository: Path = ROOT,
    *,
    tree: str | None = None,
    files_root: Path | None = None,
) -> None:
    if tree is not None:
        require(files_root is not None, "Tree validation requires a materialized filesystem root")
        for entry in _candidate_tree_entries(repository, tree):
            _require_regular_tree_entry(entry)
            _require_regular_materialized_path(files_root, entry.relative_path)
        return

    require(files_root is None, "files_root requires an explicit candidate tree")
    result = git(repository, "ls-files", "--stage", "-z")
    require(result.returncode == 0, f"Could not inspect tracked release files: {result.stderr.strip()}")
    for raw_entry in result.stdout.split("\0"):
        if not raw_entry:
            continue
        metadata, separator, relative_path = raw_entry.partition("\t")
        require(bool(separator), "Unexpected git index output during release validation")
        fields = metadata.split()
        require(len(fields) == 3, "Unexpected git index metadata during release validation")
        mode, _object_id, stage = fields
        require(
            stage == "0" and mode in {"100644", "100755"},
            f"Tracked release entry is not a regular file: "
            f"{relative_path} (mode={mode}, stage={stage})",
        )
        _require_regular_materialized_path(repository, relative_path)


def validate_final_history(
    repository: Path = ROOT,
    *,
    legacy_merge_base: str = FROZEN_V1_LEGACY_MERGE_BASE,
    contract: Mapping[str, Any] | None = None,
    candidate_ref: str = "HEAD",
    context: Literal["prepare", "final"] = "final",
) -> None:
    if contract is not None:
        try:
            validate_history_policy(
                contract,
                repository,
                candidate_ref=candidate_ref,
                context=context,
            )
        except ContractValidationError as exc:
            raise ReleaseValidationError(str(exc)) from exc
        return
    require(context == "final", "Contract-free history validation supports final context only")

    shallow = git(repository, "rev-parse", "--is-shallow-repository")
    require(shallow.returncode == 0, f"Could not inspect repository depth: {shallow.stderr.strip()}")
    require(shallow.stdout.strip() == "false", "Final release validation requires complete, non-shallow history")
    count = git(repository, "rev-list", "--count", "HEAD")
    require(count.returncode == 0, f"Could not count final release history: {count.stderr.strip()}")
    require(count.stdout.strip() == "1", "Final release history must contain exactly one root commit")
    commit_object = git(repository, "cat-file", "-p", "HEAD^{commit}")
    require(commit_object.returncode == 0, f"Could not inspect final commit: {commit_object.stderr.strip()}")
    require(
        not any(line.startswith("parent ") for line in commit_object.stdout.splitlines()),
        "Final release commit must be parentless",
    )

    head = git(repository, "rev-parse", "HEAD^{commit}")
    main = git(repository, "rev-parse", "refs/remotes/origin/main^{commit}")
    tag = git(repository, "rev-parse", f"refs/tags/{FROZEN_V1_RELEASE_REF}^{{commit}}")
    require(head.returncode == 0, f"Could not resolve final HEAD: {head.stderr.strip()}")
    require(main.returncode == 0, "Final release requires refs/remotes/origin/main")
    require(tag.returncode == 0, f"Final release tag does not exist: {FROZEN_V1_RELEASE_REF}")
    require(
        head.stdout.strip() == main.stdout.strip() == tag.stdout.strip(),
        f"HEAD, origin/main, and {FROZEN_V1_RELEASE_REF} must resolve to the same commit",
    )
    tag_type = git(repository, "cat-file", "-t", f"refs/tags/{FROZEN_V1_RELEASE_REF}")
    require(tag_type.returncode == 0, f"Could not inspect final release tag object: {tag_type.stderr.strip()}")
    require(
        tag_type.stdout.strip() == "tag",
        f"{FROZEN_V1_RELEASE_REF} must be an annotated tag, not a lightweight tag",
    )
    tag_message = git(
        repository,
        "for-each-ref",
        "--format=%(contents)",
        f"refs/tags/{FROZEN_V1_RELEASE_REF}",
    )
    require(tag_message.returncode == 0, f"Could not inspect final tag annotation: {tag_message.stderr.strip()}")
    require(
        tag_message.stdout.strip() == FROZEN_V1_RELEASE_TAG_MESSAGE,
        f"{FROZEN_V1_RELEASE_REF} annotation must exactly match the reviewed neutral release message",
    )
    legacy_exists = git(repository, "cat-file", "-e", f"{legacy_merge_base}^{{commit}}")
    if legacy_exists.returncode == 0:
        ancestor = git(repository, "merge-base", "--is-ancestor", legacy_merge_base, "HEAD")
        require(
            ancestor.returncode == 1,
            f"Legacy merge base remains an ancestor of {FROZEN_V1_RELEASE_REF}",
        )

    forbidden_refs = (
        f"refs/heads/{FROZEN_V1_RELEASE_BRANCH}",
        f"refs/remotes/origin/{FROZEN_V1_RELEASE_BRANCH}",
        "refs/tags/v0.1.0",
    )
    for reference in forbidden_refs:
        present = git(repository, "show-ref", "--verify", "--quiet", reference)
        require(present.returncode == 1, f"Stale release reference remains: {reference}")

    remote_refs = git(repository, "for-each-ref", "--format=%(refname)", "refs/remotes/origin")
    require(remote_refs.returncode == 0, "Could not inspect fetched remote-tracking branches")
    remote_ref_names = {line for line in remote_refs.stdout.splitlines() if line}
    require(
        remote_ref_names - {"refs/remotes/origin/HEAD"} == {"refs/remotes/origin/main"},
        f"Unexpected fetched remote-tracking branches remain: {remote_ref_names}",
    )
    remote_head = git(repository, "symbolic-ref", "-q", "refs/remotes/origin/HEAD")
    require(remote_head.returncode in {0, 1}, "Could not inspect origin/HEAD")
    if remote_head.returncode == 0:
        require(remote_head.stdout.strip() == "refs/remotes/origin/main", "origin/HEAD does not point to origin/main")

    tag_refs = git(repository, "for-each-ref", "--format=%(refname)", "refs/tags")
    require(tag_refs.returncode == 0, "Could not inspect fetched tags")
    require(
        {line for line in tag_refs.stdout.splitlines() if line}
        == {f"refs/tags/{FROZEN_V1_RELEASE_REF}"},
        "Final release clone contains unexpected local tags",
    )


def validate_required_paths(
    contract: Mapping[str, Any],
    root: Path = ROOT,
) -> None:
    for relative_path in contract["required_paths"]:
        require((root / relative_path).is_file(), f"Missing contracted release artifact: {relative_path}")
    require(not (root / "additional_requested_analyses.ipynb").exists(), "Temporary notebook filename remains")


def requires_stage2_metadata(contract: Mapping[str, Any]) -> bool:
    """Require Stage 2 for successor releases while exempting immutable historical v1."""

    declared_stage2_paths = set(contract.get("required_paths", ())) & STAGE2_REQUIRED_PATHS
    if (
        contract.get("release_ref") == FROZEN_V1_RELEASE_REF
        and contract.get("audited_commit") == FROZEN_V1_RELEASE_COMMIT
    ):
        require(
            not declared_stage2_paths,
            "The immutable historical v1 contract must not declare post-release Stage 2 paths",
        )
        return False
    require(
        declared_stage2_paths == STAGE2_REQUIRED_PATHS,
        "Every successor release contract must declare the complete Stage 2 "
        "metadata contract set",
    )
    return True


def validate_candidate_checksums(
    root: Path,
    *,
    repository: Path | None = None,
    tree: str | None = None,
) -> int:
    """Verify the exact checksum inventory inside a materialized candidate."""

    checksum_file = root / "checksums/SHA256SUMS"
    require(
        (repository is None) == (tree is None),
        "Candidate checksum tree validation requires both repository and tree",
    )
    tracked_files = None
    if repository is not None and tree is not None:
        entries = _candidate_tree_entries(repository, tree)
        for entry in entries:
            _require_regular_tree_entry(entry)
        tracked_files = [entry.relative_path for entry in entries]
    try:
        return verify_checksums(
            checksum_file,
            root,
            tracked_files=tracked_files,
        )
    except (OSError, ValueError) as exc:
        raise ReleaseValidationError(f"Candidate checksum validation failed: {exc}") from exc


def validate_clean_tree(repository: Path = ROOT) -> None:
    status = git(
        repository,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    require(status.returncode == 0, f"Could not inspect governance checkout: {status.stderr.strip()}")
    require(not status.stdout, "Release validation requires a clean tracked and untracked working tree")


def validate_governance_delta(
    repository: Path,
    candidate_commit: str,
    contract_path: Path,
) -> str:
    """Require one post-candidate commit containing only the contract and checksums."""

    repository = repository.resolve()
    requested_contract = contract_path if contract_path.is_absolute() else repository / contract_path
    try:
        contract_relative = requested_contract.resolve().relative_to(repository).as_posix()
    except ValueError as exc:
        raise ReleaseValidationError(
            f"Governance contract must be inside the repository: {contract_path}"
        ) from exc

    head = git(repository, "rev-parse", "--verify", "HEAD^{commit}")
    require(head.returncode == 0, f"Could not resolve governance HEAD: {head.stderr.strip()}")
    governance_commit = head.stdout.strip()
    parents = git(repository, "rev-list", "--parents", "-n", "1", governance_commit)
    require(parents.returncode == 0, f"Could not inspect governance parents: {parents.stderr.strip()}")
    require(
        parents.stdout.split() == [governance_commit, candidate_commit],
        "Governance HEAD must be the direct single-parent child of the release candidate",
    )

    changed = git(
        repository,
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "-r",
        "-z",
        candidate_commit,
        governance_commit,
    )
    require(changed.returncode == 0, f"Could not inspect governance delta: {changed.stderr.strip()}")
    changed_paths = {path for path in changed.stdout.split("\0") if path}
    allowed_paths = {contract_relative, "checksums/SHA256SUMS"}
    require(
        changed_paths == allowed_paths,
        "Governance commit must change exactly the selected release contract and "
        f"checksums/SHA256SUMS; observed {sorted(changed_paths)}",
    )

    contract_at_candidate = git(repository, "cat-file", "-e", f"{candidate_commit}:{contract_relative}")
    require(
        contract_at_candidate.returncode != 0,
        "Selected post-release contract must be absent from the release candidate",
    )
    for revision, relative in (
        (candidate_commit, "checksums/SHA256SUMS"),
        (governance_commit, contract_relative),
        (governance_commit, "checksums/SHA256SUMS"),
    ):
        present = git(repository, "cat-file", "-e", f"{revision}:{relative}")
        require(
            present.returncode == 0,
            f"Required governance path is missing at {revision}: {relative}",
        )
    return governance_commit


def validate_data(root: Path = ROOT) -> dict[str, object]:
    """Run the frozen, offline semantic data checks in one filesystem root."""

    return {
        "workbooks": validate_source_workbooks(root),
        "dataset": validate_canonical_dataset(root),
        "threshold": validate_threshold_artifacts(root),
        "configuration": validate_configs_and_prompts(root),
    }


def validate_release_candidate(
    contract_path: Path,
    *,
    mode: Literal["prepare", "final"],
    candidate_ref: str,
    repository: Path = ROOT,
) -> dict[str, object]:
    """Validate a release using governance tooling against the exact candidate tree."""

    validate_clean_tree(repository)
    with materialized_candidate(repository, candidate_ref) as candidate:
        governance_commit = validate_governance_delta(
            repository,
            candidate.commit,
            contract_path,
        )
        contract = validate_release_contract(
            contract_path,
            repository,
            check_current_files=True,
            context=mode,
            candidate_ref=candidate.commit,
            current_files_root=candidate.root,
        )
        validate_tracked_file_types(
            repository,
            tree=candidate.tree,
            files_root=candidate.root,
        )
        validate_required_paths(contract, candidate.root)
        stage2_metadata_required = requires_stage2_metadata(contract)
        checksum_count = validate_candidate_checksums(
            candidate.root,
            repository=repository,
            tree=candidate.tree,
        )
        summary = validate_data(candidate.root)
        if stage2_metadata_required:
            summary["metadata_contracts"] = validate_metadata_contracts(
                candidate.root,
                schema_root=repository,
            )
        validate_notebooks(candidate.root)
        summary["manifest"] = validate_manifest(candidate.root)["manifest_id"]
        validate_documentation(mode, contract, candidate.root)
        validate_history_policy(
            contract,
            repository,
            context=mode,
            candidate_ref=candidate.commit,
        )
        summary.update(
            {
                "contract": contract_path.as_posix(),
                "candidate_ref": candidate.requested_ref,
                "candidate_commit": candidate.commit,
                "candidate_tree": candidate.tree,
                "candidate_checksum_entries": checksum_count,
                "governance_commit": governance_commit,
                "release_mode": mode,
            }
        )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--data-only", action="store_true")
    mode.add_argument("--release", action="store_true")
    parser.add_argument("--mode", choices=("prepare", "final"), default="prepare")
    parser.add_argument("--contract", type=Path, help="Versioned release contract for release validation")
    parser.add_argument("--ref", help="Candidate Git ref for release validation")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        require(
            not args.release or args.contract is not None,
            "--release requires an explicit --contract",
        )
        require(
            not args.release or args.ref is not None,
            "--release requires an explicit --ref",
        )
        if args.release:
            summary = validate_release_candidate(
                args.contract,
                mode=args.mode,
                candidate_ref=args.ref,
                repository=ROOT,
            )
        else:
            summary = validate_data(ROOT)
    except (
        KeyError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        jsonschema.ValidationError,
        ContractValidationError,
        MetadataValidationError,
        ReleaseValidationError,
    ) as exc:
        print(f"Release validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
