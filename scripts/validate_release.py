#!/usr/bin/env python3
"""Validate frozen data and release metadata without network or API access."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import jsonschema
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
ARTICLE_TITLE = "Large language models generate diagnostic likelihood ratios with low mean bias but wide dispersion"
ARTICLE_DOI = "10.1038/s41598-026-61766-2"
RELEASE_VERSION = "1.0.0"
RELEASE_REF = "v1.0.0"
RELEASE_TAG_MESSAGE = "Accepted-paper reproducibility release"
LEGACY_MERGE_BASE = "9ab48f0244daff1b7c9ed58f2f4fca2572284f65"
RELEASE_BRANCH = "release/accepted-paper-reproducibility-v1"
PUBLISHER_URL = "https://doi.org/10.1038/s41598-026-61766-2"
PUBLISHED_DATE = "2026-07-11"

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

REQUIRED_RELEASE_PATHS = (
    ".python-version",
    "CHANGELOG.md",
    "CITATION.cff",
    "CONTRIBUTING.md",
    "Makefile",
    "README.md",
    "RELEASE_NOTES_v1.0.0.md",
    "checksums/SHA256SUMS",
    "config/analysis_categories_v1.json",
    "config/manuscript_models_v1.json",
    "data/README.md",
    "data/curated/diagnostic_lrs_manuscript_v1.csv",
    "data/model_outputs/manuscript_model_outputs_v1.csv",
    "data/model_outputs/manuscript_query_run_v1.csv",
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_cases.csv",
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_raw.csv",
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_reviewer_table.csv",
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_summary.csv",
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_summary.md",
    "data/provenance/curation_log_v1.csv",
    "data/provenance/provenance_gaps_v1.csv",
    "data/provenance/source_crosswalk_v1.csv",
    "docs/ACCEPTED_PAPER_CROSSWALK.md",
    "docs/DATA_PROVENANCE.md",
    "docs/REPLICATION.md",
    "docs/REPRODUCIBILITY.md",
    "docs/RELEASE_PROCESS.md",
    "llms-full.txt",
    "llms.txt",
    "manifests/manifest.schema.json",
    "manifests/manuscript_run_v1.json",
    "prompts/main_estimator_v1.json",
    "prompts/threshold_perturbation_v1.json",
    "results/reference/main_metrics.json",
    "results/reference/pairwise_model_comparisons.csv",
    "results/reference/coverage_intervals.csv",
    "results/reference/evidence_direction_tests.csv",
    "scripts/build_checksums.py",
    "scripts/build_release_assets.py",
    "scripts/reproduce_paper.py",
    "supplementary_analyses.ipynb",
    "tools/cff/.python-version",
    "tools/cff/pyproject.toml",
    "tools/cff/uv.lock",
)

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
    )


def boolean_sum(series: pd.Series) -> int:
    if pd.api.types.is_bool_dtype(series):
        return int(series.sum())
    normalized = series.astype(str).str.strip().str.lower()
    require(normalized.isin({"true", "false", "1", "0"}).all(), f"Invalid Boolean values in {series.name}")
    return int(normalized.isin({"true", "1"}).sum())


def validate_source_workbooks() -> dict[str, str]:
    observed: dict[str, str] = {}
    for relative_path, expected_hash in WORKBOOK_HASHES.items():
        path = ROOT / relative_path
        require(path.is_file(), f"Missing source workbook: {relative_path}")
        observed_hash = sha256(path)
        require(observed_hash == expected_hash, f"Source workbook hash changed: {relative_path}")
        observed[relative_path] = observed_hash
    return observed


def validate_canonical_dataset() -> dict[str, object]:
    canonical_path = ROOT / "data/curated/diagnostic_lrs_manuscript_v1.csv"
    require(canonical_path.is_file(), f"Missing canonical dataset: {canonical_path.relative_to(ROOT)}")
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

    output_path = ROOT / "data/model_outputs/manuscript_model_outputs_v1.csv"
    outputs = pd.read_csv(output_path)
    require(len(outputs) == 700, f"Manuscript model output table must have 700 rows, found {len(outputs)}")
    require(outputs["row_id"].tolist() == expected_ids, "Model output row IDs or order changed")
    for column in MODEL_COLUMNS:
        left = pd.to_numeric(frame[column], errors="raise").to_numpy(dtype=float)
        right = pd.to_numeric(outputs[column], errors="raise").to_numpy(dtype=float)
        require(np.array_equal(left, right), f"Frozen model outputs differ in {column}")

    crosswalk = pd.read_csv(ROOT / "data/provenance/source_crosswalk_v1.csv")
    require(len(crosswalk) == 700, f"Source crosswalk must have 700 rows, found {len(crosswalk)}")
    require(crosswalk["row_id"].tolist() == expected_ids, "Source crosswalk row IDs or order changed")

    return {
        "rows": len(frame),
        "conditions": condition_count,
        "model_values": len(frame) * len(MODEL_COLUMNS),
        "category_counts": category_counts,
        "feature_counts": feature_counts,
    }


def validate_threshold_artifacts() -> dict[str, int]:
    base = ROOT / "data/model_outputs/threshold_perturbation_v1"
    expected_rows = {
        "threshold_perturbation_cases.csv": 15,
        "threshold_perturbation_raw.csv": 15,
        "threshold_perturbation_summary.csv": 5,
        "threshold_perturbation_reviewer_table.csv": 5,
    }
    observed: dict[str, int] = {}
    for filename, row_count in expected_rows.items():
        path = base / filename
        require(path.is_file(), f"Missing frozen threshold artifact: {path.relative_to(ROOT)}")
        frame = pd.read_csv(path)
        require(len(frame) == row_count, f"{filename} must have {row_count} rows, found {len(frame)}")
        observed[filename] = len(frame)

    raw = pd.read_csv(base / "threshold_perturbation_raw.csv")
    estimates = pd.to_numeric(raw["lr_estimate"], errors="coerce").to_numpy(dtype=float)
    require(np.isfinite(estimates).all() and (estimates > 0).all(), "Threshold estimates must be positive and finite")
    require((raw["error_status"].astype(str).str.lower() == "ok").all(), "Accepted threshold run contains failed calls")
    return observed


def validate_configs_and_prompts() -> dict[str, object]:
    models = json.loads((ROOT / "config/manuscript_models_v1.json").read_text(encoding="utf-8"))
    configured_models = tuple(item["api_model"] for item in models["manuscript_models"])
    require(configured_models == MODEL_IDS, f"Manuscript model scope changed: {configured_models}")

    main_prompt = json.loads((ROOT / "prompts/main_estimator_v1.json").read_text(encoding="utf-8"))
    threshold_prompt = json.loads((ROOT / "prompts/threshold_perturbation_v1.json").read_text(encoding="utf-8"))
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


def validate_notebooks() -> None:
    for relative_path in NOTEBOOKS:
        path = ROOT / relative_path
        require(path.is_file(), f"Missing notebook: {relative_path}")
        notebook = json.loads(path.read_text(encoding="utf-8"))
        for index, cell in enumerate(notebook.get("cells", [])):
            if cell.get("cell_type") != "code":
                continue
            require(cell.get("execution_count") is None, f"Stored execution count in {relative_path} cell {index}")
            require(cell.get("outputs", []) == [], f"Stored output in {relative_path} cell {index}")


def validate_manifest() -> dict[str, object]:
    manifest = json.loads((ROOT / "manifests/manuscript_run_v1.json").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "manifests/manifest.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(manifest, schema)
    require(manifest["release_version"] == RELEASE_VERSION, "Manifest release version is inconsistent")
    require(manifest["release_ref"] == RELEASE_REF, "Manifest release ref is inconsistent")
    require(manifest["article"]["doi"] == ARTICLE_DOI, "Manifest article DOI is inconsistent")
    require(manifest["article"]["published_date"] == PUBLISHED_DATE, "Manifest publication date is inconsistent")
    require(
        manifest["article"]["publication_status"] == "published_unedited_early_access",
        "Manifest article publication status is inconsistent",
    )
    require(manifest["article"]["publisher_url"] == PUBLISHER_URL, "Manifest publisher URL is inconsistent")
    return manifest


def validate_documentation(mode: str) -> None:
    cff = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    require(str(cff["version"]) == RELEASE_VERSION, "CITATION.cff version is inconsistent")
    require(cff["preferred-citation"]["doi"] == ARTICLE_DOI, "CITATION.cff article DOI is inconsistent")
    require(cff["preferred-citation"]["title"] == ARTICLE_TITLE, "CITATION.cff article title is inconsistent")
    require(
        str(cff["preferred-citation"]["date-published"]) == PUBLISHED_DATE,
        "CITATION.cff article publication date is inconsistent",
    )
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    require(pyproject["project"]["urls"]["Homepage"] == PUBLISHER_URL, "Package homepage must be the article DOI URL")

    required_text_paths = (
        "README.md",
        "RELEASE_NOTES_v1.0.0.md",
        "llms.txt",
        "docs/REPRODUCIBILITY.md",
    )
    for relative_path in required_text_paths:
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        require(ARTICLE_DOI in text, f"Article DOI missing from {relative_path}")

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if mode == "prepare":
        require("date-released" not in cff, "Prepare-mode CITATION.cff must not claim a release date")
        require("## [1.0.0] - Unreleased" in changelog, "Prepare-mode changelog must remain Unreleased")
    else:
        require("date-released" in cff, "Final CITATION.cff requires date-released")
        release_date = str(cff["date-released"])
        require(
            f"## [1.0.0] - {release_date}" in changelog,
            "Final changelog date must match CITATION.cff date-released",
        )
        require("Unreleased" not in changelog, "Final changelog still contains Unreleased metadata")
        pending_phrases = (
            "until the tag is published",
            "prepared release identifier",
            "describe a prepared release",
            "do not assert that the `v1.0.0` tag",
        )
        for relative_path in ("README.md", "llms.txt", "RELEASE_NOTES_v1.0.0.md"):
            normalized = (ROOT / relative_path).read_text(encoding="utf-8").casefold()
            require(
                not any(phrase in normalized for phrase in pending_phrases),
                f"Final release metadata remains pending in {relative_path}",
            )
        tag = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/tags/{RELEASE_REF}^{{commit}}"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        require(tag.returncode == 0, f"Final release tag does not exist: {RELEASE_REF}")
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        require(tag.stdout.strip() == head.stdout.strip(), f"{RELEASE_REF} does not resolve to current HEAD")
        legacy_tag = subprocess.run(
            ["git", "rev-parse", "--verify", "refs/tags/v0.1.0"],
            cwd=ROOT,
            check=False,
            capture_output=True,
        )
        require(legacy_tag.returncode != 0, "Legacy v0.1.0 tag remains at final release")


def validate_tracked_file_types(repository: Path = ROOT) -> None:
    result = git(repository, "ls-files", "--stage", "-z")
    require(result.returncode == 0, f"Could not inspect tracked release files: {result.stderr.strip()}")
    for raw_entry in result.stdout.split("\0"):
        if not raw_entry:
            continue
        metadata, separator, relative = raw_entry.partition("\t")
        require(bool(separator), "Unexpected git index output during release validation")
        fields = metadata.split()
        require(len(fields) == 3, "Unexpected git index metadata during release validation")
        mode, _object_id, stage = fields
        require(
            stage == "0" and mode in {"100644", "100755"},
            f"Tracked release entry is not a regular file: {relative} (mode={mode}, stage={stage})",
        )
        path = repository / relative
        try:
            observed_mode = path.lstat().st_mode
        except FileNotFoundError as exc:
            raise ReleaseValidationError(f"Tracked release file is missing: {relative}") from exc
        require(
            not path.is_symlink() and stat.S_ISREG(observed_mode),
            f"Tracked release entry is not a regular working-tree file: {relative}",
        )


def validate_final_history(
    repository: Path = ROOT,
    *,
    legacy_merge_base: str = LEGACY_MERGE_BASE,
) -> None:
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
    tag = git(repository, "rev-parse", f"refs/tags/{RELEASE_REF}^{{commit}}")
    require(head.returncode == 0, f"Could not resolve final HEAD: {head.stderr.strip()}")
    require(main.returncode == 0, "Final release requires refs/remotes/origin/main")
    require(tag.returncode == 0, f"Final release tag does not exist: {RELEASE_REF}")
    require(
        head.stdout.strip() == main.stdout.strip() == tag.stdout.strip(),
        f"HEAD, origin/main, and {RELEASE_REF} must resolve to the same commit",
    )
    tag_type = git(repository, "cat-file", "-t", f"refs/tags/{RELEASE_REF}")
    require(tag_type.returncode == 0, f"Could not inspect final release tag object: {tag_type.stderr.strip()}")
    require(tag_type.stdout.strip() == "tag", f"{RELEASE_REF} must be an annotated tag, not a lightweight tag")
    tag_message = git(repository, "for-each-ref", "--format=%(contents)", f"refs/tags/{RELEASE_REF}")
    require(tag_message.returncode == 0, f"Could not inspect final tag annotation: {tag_message.stderr.strip()}")
    require(
        tag_message.stdout.strip() == RELEASE_TAG_MESSAGE,
        f"{RELEASE_REF} annotation must exactly match the reviewed neutral release message",
    )
    legacy_exists = git(repository, "cat-file", "-e", f"{legacy_merge_base}^{{commit}}")
    if legacy_exists.returncode == 0:
        ancestor = git(repository, "merge-base", "--is-ancestor", legacy_merge_base, "HEAD")
        require(ancestor.returncode == 1, f"Legacy merge base remains an ancestor of {RELEASE_REF}")

    forbidden_refs = (
        f"refs/heads/{RELEASE_BRANCH}",
        f"refs/remotes/origin/{RELEASE_BRANCH}",
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
        {line for line in tag_refs.stdout.splitlines() if line} == {f"refs/tags/{RELEASE_REF}"},
        "Final release clone contains unexpected local tags",
    )


def validate_required_paths() -> None:
    for relative_path in REQUIRED_RELEASE_PATHS:
        require((ROOT / relative_path).is_file(), f"Missing release artifact: {relative_path}")
    require(not (ROOT / "AGENTS.md").exists(), "AGENTS.md must not be present in the public release")
    require(not (ROOT / "additional_requested_analyses.ipynb").exists(), "Temporary notebook filename remains")


def validate_clean_tree() -> None:
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    require(not status.stdout, "Release validation requires a clean tracked and untracked working tree")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--data-only", action="store_true")
    mode.add_argument("--release", action="store_true")
    parser.add_argument("--mode", choices=("prepare", "final"), default="prepare")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary = {
            "workbooks": validate_source_workbooks(),
            "dataset": validate_canonical_dataset(),
            "threshold": validate_threshold_artifacts(),
            "configuration": validate_configs_and_prompts(),
        }
        if args.release:
            validate_clean_tree()
            validate_tracked_file_types()
            validate_required_paths()
            validate_notebooks()
            summary["manifest"] = validate_manifest()["manifest_id"]
            validate_documentation(args.mode)
            if args.mode == "final":
                validate_final_history()
            summary["release_mode"] = args.mode
    except (
        KeyError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        jsonschema.ValidationError,
        ReleaseValidationError,
    ) as exc:
        print(f"Release validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
