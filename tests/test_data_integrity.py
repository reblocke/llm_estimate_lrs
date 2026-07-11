from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.build_release_dataset import (
    MASTER_SHA256,
    PER_CONDITION_SHA256,
    THRESHOLD_FILES,
    build_release_dataset,
)

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "data/curated/diagnostic_lrs_manuscript_v1.csv"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_source_workbooks_and_canonical_contract() -> None:
    assert sha256(ROOT / "NNT_LRs_08-26-2025.xlsx") == MASTER_SHA256
    assert sha256(ROOT / "nnt_lrs_with_estimated.xlsx") == PER_CONDITION_SHA256

    data = pd.read_csv(CANONICAL)
    assert len(data) == 700
    assert data["row_id"].tolist() == [f"lr_{index:04d}" for index in range(1, 701)]
    assert data["row_id"].is_unique
    assert data["master_row_number"].tolist() == list(range(2, 702))
    assert data["condition_full"].nunique() == 30
    assert (data["condition_full"] == data["condition_full"].str.strip()).all()

    numeric_columns = [
        "lr_reported",
        "lr_gpt-4o-2024-11-20",
        "lr_o3-2025-04-16",
        "lr_gpt-5",
    ]
    numeric = data[numeric_columns].to_numpy(dtype=float)
    assert np.isfinite(numeric).all()
    assert (numeric > 0).all()

    assert data["reported_qualitative_band"].value_counts().to_dict() == {
        "Strong Negative": 17,
        "Moderate Negative": 22,
        "Weak Negative": 60,
        "Negligible": 400,
        "Weak Positive": 120,
        "Moderate Positive": 52,
        "Strong Positive": 29,
    }
    assert {column: int(data[column].sum()) for column in data.columns if column.startswith("is_")} == {
        "is_sign_or_symptom": 416,
        "is_history": 134,
        "is_test_result": 110,
        "is_imaging": 57,
        "is_diagnostic_adjudication": 8,
    }


def test_outputs_crosswalk_and_provenance_are_complete() -> None:
    data = pd.read_csv(CANONICAL)
    expected_ids = data["row_id"].tolist()

    outputs = pd.read_csv(ROOT / "data/model_outputs/manuscript_model_outputs_v1.csv")
    assert outputs.columns.tolist() == [
        "row_id",
        "lr_gpt-4o-2024-11-20",
        "lr_o3-2025-04-16",
        "lr_gpt-5",
    ]
    assert outputs["row_id"].tolist() == expected_ids
    np.testing.assert_array_equal(
        outputs.iloc[:, 1:].to_numpy(dtype=float),
        data[outputs.columns[1:]].to_numpy(dtype=float),
    )

    auxiliary = pd.read_csv(ROOT / "data/model_outputs/auxiliary_gpt-4.1_outputs_v1.csv")
    assert auxiliary["row_id"].tolist() == expected_ids
    assert set(auxiliary["accepted_manuscript_role"]) == {"auxiliary_historical_not_analyzed"}

    crosswalk = pd.read_csv(ROOT / "data/provenance/source_crosswalk_v1.csv")
    assert crosswalk["row_id"].tolist() == expected_ids
    assert set(crosswalk["match_status"]) == {"exact_occurrence_match"}
    duplicated = crosswalk[crosswalk["master_key_count"] == 2]
    assert len(duplicated) == 2
    assert duplicated["match_occurrence"].tolist() == [1, 2]
    assert (crosswalk["master_key_count"] == crosswalk["source_key_count"]).all()

    curation = pd.read_csv(ROOT / "data/provenance/curation_log_v1.csv")
    assert curation.empty
    gaps = pd.read_csv(ROOT / "data/provenance/provenance_gaps_v1.csv")
    assert gaps["gap_id"].tolist() == [f"PG-{index:03d}" for index in range(1, 9)]
    assert not gaps["blocking_for_reproduction"].astype(bool).any()


def test_query_audit_does_not_invent_missing_metadata() -> None:
    audit = pd.read_csv(ROOT / "data/model_outputs/manuscript_query_run_v1.csv")
    assert audit["api_model"].tolist() == ["gpt-4o-2024-11-20", "o3-2025-04-16", "gpt-5"]
    assert audit["query_date"].astype(str).tolist() == ["2025-08-25"] * 3
    assert audit["run_id"].isna().all()
    assert audit["sdk_version"].isna().all()
    assert not audit["response_ids_available"].any()
    assert not audit["retry_audit_available"].any()


def test_threshold_artifacts_are_exact_accepted_files() -> None:
    base = ROOT / "data/model_outputs/threshold_perturbation_v1"
    for filename, expected_hash in THRESHOLD_FILES.items():
        assert sha256(base / filename) == expected_hash

    cases = pd.read_csv(base / "threshold_perturbation_cases.csv")
    raw = pd.read_csv(base / "threshold_perturbation_raw.csv")
    summary = pd.read_csv(base / "threshold_perturbation_summary.csv")
    response = pd.read_csv(base / "threshold_perturbation_reviewer_table.csv")
    assert (len(cases), len(raw), len(summary), len(response)) == (15, 15, 5, 5)
    assert np.isfinite(raw["lr_estimate"]).all()
    assert (raw["lr_estimate"] > 0).all()
    assert raw["error_status"].eq("ok").all()
    assert {"monotonic_class", "anchored_flag"}.issubset(summary.columns)
    assert summary["monotonic_class"].value_counts().to_dict() == {
        "nonmonotonic": 2,
        "strictly_increasing": 2,
        "nondecreasing_with_ties": 1,
    }
    assert not summary["anchored_flag"].any()


def test_release_dataset_builder_is_byte_deterministic(tmp_path: Path) -> None:
    generated = build_release_dataset(
        master_workbook=ROOT / "NNT_LRs_08-26-2025.xlsx",
        per_condition_workbook=ROOT / "nnt_lrs_with_estimated.xlsx",
        output_root=tmp_path,
        category_config=ROOT / "config/analysis_categories_v1.json",
        threshold_source_dir=ROOT / "data/model_outputs/threshold_perturbation_v1",
    )
    tracked_by_key = {
        "canonical": CANONICAL,
        "model_outputs": ROOT / "data/model_outputs/manuscript_model_outputs_v1.csv",
        "auxiliary_outputs": ROOT / "data/model_outputs/auxiliary_gpt-4.1_outputs_v1.csv",
        "query_audit": ROOT / "data/model_outputs/manuscript_query_run_v1.csv",
        "crosswalk": ROOT / "data/provenance/source_crosswalk_v1.csv",
        "curation_log": ROOT / "data/provenance/curation_log_v1.csv",
        "provenance_gaps": ROOT / "data/provenance/provenance_gaps_v1.csv",
    }
    for key, tracked in tracked_by_key.items():
        assert generated[key].read_bytes() == tracked.read_bytes()
    for filename in THRESHOLD_FILES:
        key = f"threshold_{filename}"
        assert (
            generated[key].read_bytes()
            == (ROOT / "data/model_outputs/threshold_perturbation_v1" / filename).read_bytes()
        )
