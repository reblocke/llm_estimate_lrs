from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.compute_reference_results import compute_reference_results
from scripts.reproduce_paper import compare_reference_artifacts

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "results/reference"


def row_by_model(frame: pd.DataFrame, model: str) -> pd.Series:
    return frame.set_index("api_model").loc[model]


def test_reference_results_match_accepted_contract() -> None:
    main = json.loads((REFERENCE / "main_metrics.json").read_text(encoding="utf-8"))
    dataset = main["dataset"]
    reported = dataset["reported_lr"]
    assert dataset["rows"] == 700
    assert dataset["conditions"] == 30
    assert reported["minimum"] == 0.01
    assert np.isclose(reported["maximum"], 145.8937969894539)
    assert reported["median"] == 1.0
    assert np.isclose(reported["percentile_25"], 0.7)
    assert np.isclose(reported["percentile_75"], 2.2)
    assert np.isclose(reported["geometric_mean"], 1.2058004154886994)

    agreement = pd.read_csv(REFERENCE / "agreement_metrics.csv")
    expected_agreement = {
        "gpt-4o-2024-11-20": (1.018, 0.229, 4.527),
        "o3-2025-04-16": (0.987, 0.227, 4.281),
        "gpt-5": (0.988, 0.264, 3.703),
    }
    for model, expected in expected_agreement.items():
        row = row_by_model(agreement, model)
        np.testing.assert_allclose(
            [row["mean_multiplicative_bias"], row["lower_95_limit"], row["upper_95_limit"]],
            expected,
            atol=0.001,
        )

    reliability = pd.read_csv(REFERENCE / "reliability_metrics.csv")
    expected_reliability = {
        "gpt-4o-2024-11-20": (0.734, 0.655),
        "o3-2025-04-16": (0.763, 0.645),
        "gpt-5": (0.877, 0.675),
    }
    for model, expected in expected_reliability.items():
        row = row_by_model(reliability, model)
        np.testing.assert_allclose([row["reliability_slope"], row["reliability_r_squared"]], expected, atol=0.001)

    kappa = pd.read_csv(REFERENCE / "kappa_metrics.csv")
    expected_kappa = {
        "gpt-4o-2024-11-20": 0.734,
        "o3-2025-04-16": 0.745,
        "gpt-5": 0.775,
    }
    for model, expected in expected_kappa.items():
        assert np.isclose(row_by_model(kappa, model)["weighted_kappa"], expected, atol=0.001)


def test_reliability_zones_and_laboratory_flags() -> None:
    zones = pd.read_csv(REFERENCE / "reliability_zone_metrics.csv")
    assert zones.groupby("zone")["n"].first().to_dict() == {
        "Central reliability zone": 585,
        "Extreme LR zone": 115,
    }
    gpt5 = zones[zones["api_model"] == "gpt-5"].set_index("zone")
    np.testing.assert_allclose(
        [
            gpt5.loc["Central reliability zone", "median_abs_log_error"],
            gpt5.loc["Extreme LR zone", "median_abs_log_error"],
            gpt5.loc["Central reliability zone", "rmse_log"],
            gpt5.loc["Extreme LR zone", "rmse_log"],
        ],
        [0.182, 0.588, 0.565, 1.065],
        atol=0.001,
    )

    flags = json.loads((REFERENCE / "laboratory_discrepancy_flags.json").read_text(encoding="utf-8"))
    assert flags["n"] == 10
    assert flags["threshold_present"] == 5
    assert flags["unit_present"] == 3
    assert flags["extreme_reported_lr"] == 6
    assert len(flags["top_10_row_ids"]) == 10


def test_pairwise_bias_and_dispersion_comparisons() -> None:
    pairwise = pd.read_csv(REFERENCE / "pairwise_model_comparisons.csv").set_index("comparison")
    assert pairwise.index.tolist() == ["GPT-4o vs o3", "GPT-4o vs GPT-5", "o3 vs GPT-5"]
    assert pairwise["n"].tolist() == [700, 700, 700]
    np.testing.assert_allclose(
        pairwise["bias_ratio"].to_numpy(),
        [1.031412038207184, 1.0296700871202016, 0.9983111006828945],
        atol=1e-12,
    )
    np.testing.assert_allclose(
        pairwise["p_t"].to_numpy(),
        [0.23198141971627242, 0.28759270467217224, 0.9329977944979265],
        atol=1e-12,
    )
    np.testing.assert_allclose(
        pairwise["pitman_morgan_p"].to_numpy(),
        [0.5809234322898589, 0.00021355695480377738, 0.000056193951494817414],
        atol=1e-12,
    )


def test_coverage_intervals_and_evidence_direction_comparisons() -> None:
    coverage = pd.read_csv(REFERENCE / "coverage_intervals.csv")
    assert len(coverage) == 15
    assert set(coverage["coverage_percent"]) == {50, 75, 90, 95, 99}
    coverage_95 = coverage[coverage["coverage_percent"] == 95].set_index("api_model")
    np.testing.assert_allclose(
        coverage_95.loc[
            ["gpt-4o-2024-11-20", "o3-2025-04-16", "gpt-5"],
            ["lower", "upper"],
        ].to_numpy(),
        [[0.229, 4.527], [0.227, 4.281], [0.264, 3.703]],
        atol=0.001,
    )

    direction = pd.read_csv(REFERENCE / "evidence_direction_tests.csv").set_index("api_model")
    assert (direction[["n_negative", "n_positive"]].to_numpy() == [341, 338]).all()
    np.testing.assert_allclose(
        direction.loc[
            ["gpt-4o-2024-11-20", "o3-2025-04-16", "gpt-5"],
            "levene_brown_forsythe_p",
        ].to_numpy(),
        [0.11, 0.40, 0.37],
        atol=0.01,
    )
    np.testing.assert_allclose(
        direction.loc[
            ["gpt-4o-2024-11-20", "o3-2025-04-16", "gpt-5"],
            "welch_p",
        ].to_numpy(),
        [0.000440231966009516, 0.14546969440582408, 0.000004442650911002815],
        rtol=1e-12,
    )


def test_reference_generation_is_semantically_deterministic(tmp_path: Path) -> None:
    generated = compute_reference_results(
        ROOT / "data/curated/diagnostic_lrs_manuscript_v1.csv",
        tmp_path,
    )
    assert set(generated) == {
        "main_metrics",
        "category_counts",
        "feature_type_counts",
        "agreement_metrics",
        "pairwise_model_comparisons",
        "coverage_intervals",
        "evidence_direction_tests",
        "calibration_metrics",
        "reliability_metrics",
        "kappa_metrics",
        "reliability_zone_metrics",
        "laboratory_discrepancy_flags",
        "readme",
    }
    comparisons = compare_reference_artifacts(REFERENCE, tmp_path)
    assert len(comparisons) == len(generated)
    assert all(comparison["status"] == "match" for comparison in comparisons)
