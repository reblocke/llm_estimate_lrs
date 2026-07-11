#!/usr/bin/env python3
"""Compute deterministic accepted-paper reference results from frozen CSV data."""

from __future__ import annotations

import argparse
import itertools
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from sklearn.metrics import confusion_matrix
from statsmodels.stats.inter_rater import cohens_kappa

MODEL_SPECS = (
    ("GPT-4o", "gpt-4o-2024-11-20", "lr_gpt-4o-2024-11-20"),
    ("GPT-5", "gpt-5", "lr_gpt-5"),
    ("o3", "o3-2025-04-16", "lr_o3-2025-04-16"),
)

QUALITATIVE_BANDS = (
    "Strong Negative",
    "Moderate Negative",
    "Weak Negative",
    "Negligible",
    "Weak Positive",
    "Moderate Positive",
    "Strong Positive",
)

REFERENCE_README = """# Frozen reference results

These compact files are computed from
`data/curated/diagnostic_lrs_manuscript_v1.csv` and form the numerical contract
for release `v1.0.0`. Run `scripts/compute_reference_results.py` to regenerate
them in a separate output directory and compare the resulting files byte for
byte.

- `main_metrics.json` describes the accepted dataset.
- `category_counts.csv` and `feature_type_counts.csv` record the descriptive
  distributions.
- `agreement_metrics.csv` records Bland-Altman reported/model ratios and
  log-scale errors.
- `pairwise_model_comparisons.csv` reproduces the paired bias,
  Pitman-Morgan variance, and Bradley-Blackwood comparisons.
- `coverage_intervals.csv` records the accepted 50%, 75%, 90%, 95%, and 99%
  multiplicative coverage intervals.
- `evidence_direction_tests.csv` reproduces the LR-below-one versus
  LR-above-one bias and dispersion comparisons.
- `calibration_metrics.csv` models log(model LR) as a function of log(reported
  LR), using the accepted deterministic bootstrap seed for confidence limits.
- `reliability_metrics.csv` reverses those axes to quantify inverse reliability
  calibration.
- `kappa_metrics.csv` records quadratic weighted qualitative agreement.
- `reliability_zone_metrics.csv` compares the prespecified central and extreme
  reported-LR zones.
- `laboratory_discrepancy_flags.json` reproduces the three descriptive counts
  among the ten largest GPT-5 lab-like discrepancies.

No file in this directory is produced from a live model or network request.
"""


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n")


def _write_json(document: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _ols(x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    design = sm.add_constant(np.asarray(x, dtype=float), has_constant="add")
    fit = sm.OLS(np.asarray(y, dtype=float), design, missing="raise").fit()
    confidence = fit.conf_int()
    return {
        "intercept": float(fit.params[0]),
        "intercept_ci_low": float(confidence[0, 0]),
        "intercept_ci_high": float(confidence[0, 1]),
        "slope": float(fit.params[1]),
        "slope_ci_low": float(confidence[1, 0]),
        "slope_ci_high": float(confidence[1, 1]),
        "r2": float(fit.rsquared),
    }


def _manual_ols(x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    x_mean = float(np.mean(x))
    y_mean = float(np.mean(y))
    x_centered = x - x_mean
    y_centered = y - y_mean
    ss_x = float(np.sum(x_centered * x_centered))
    slope = float(np.sum(x_centered * y_centered) / ss_x)
    intercept = float(y_mean - slope * x_mean)
    fitted = intercept + slope * x
    ss_total = float(np.sum((y - y_mean) ** 2))
    ss_residual = float(np.sum((y - fitted) ** 2))
    return {
        "intercept": intercept,
        "slope": slope,
        "r_squared": float(1.0 - ss_residual / ss_total),
    }


def _bootstrap_primary_calibration(
    x: np.ndarray,
    y: np.ndarray,
    rng: np.random.Generator,
    bootstrap_reps: int = 2000,
) -> dict[str, float]:
    point = _manual_ols(x, y)
    sample_indices = rng.integers(0, len(x), size=(bootstrap_reps, len(x)))
    x_bootstrap = x[sample_indices]
    y_bootstrap = y[sample_indices]
    differences = x_bootstrap - y_bootstrap
    oe_bootstrap = np.exp(np.mean(differences, axis=1))
    citl_bootstrap = np.mean(y_bootstrap - x_bootstrap, axis=1)
    x_mean = np.mean(x_bootstrap, axis=1)
    y_mean = np.mean(y_bootstrap, axis=1)
    x_centered = x_bootstrap - x_mean[:, None]
    y_centered = y_bootstrap - y_mean[:, None]
    ss_x = np.sum(x_centered * x_centered, axis=1)
    slope_bootstrap = np.divide(
        np.sum(x_centered * y_centered, axis=1),
        ss_x,
        out=np.full(bootstrap_reps, np.nan),
        where=ss_x > 0,
    )
    return {
        **point,
        "oe": float(np.exp(np.mean(x - y))),
        "oe_ci_lo": float(np.nanquantile(oe_bootstrap, 0.025)),
        "oe_ci_hi": float(np.nanquantile(oe_bootstrap, 0.975)),
        "cs": point["slope"],
        "cs_ci_lo": float(np.nanquantile(slope_bootstrap, 0.025)),
        "cs_ci_hi": float(np.nanquantile(slope_bootstrap, 0.975)),
        "citl": float(np.mean(y - x)),
        "citl_ci_lo": float(np.nanquantile(citl_bootstrap, 0.025)),
        "citl_ci_hi": float(np.nanquantile(citl_bootstrap, 0.975)),
    }


def _bootstrap_reliability(
    x: np.ndarray,
    y: np.ndarray,
    rng: np.random.Generator,
    bootstrap_reps: int = 2000,
) -> dict[str, float]:
    point = _manual_ols(x, y)
    sample_indices = rng.integers(0, len(x), size=(bootstrap_reps, len(x)))
    x_bootstrap = x[sample_indices]
    y_bootstrap = y[sample_indices]
    x_mean = np.mean(x_bootstrap, axis=1)
    y_mean = np.mean(y_bootstrap, axis=1)
    x_centered = x_bootstrap - x_mean[:, None]
    y_centered = y_bootstrap - y_mean[:, None]
    ss_x = np.sum(x_centered * x_centered, axis=1)
    slopes = np.divide(
        np.sum(x_centered * y_centered, axis=1),
        ss_x,
        out=np.full(bootstrap_reps, np.nan),
        where=ss_x > 0,
    )
    intercepts = y_mean - slopes * x_mean
    return {
        **point,
        "intercept_ci_lo": float(np.nanquantile(intercepts, 0.025)),
        "intercept_ci_hi": float(np.nanquantile(intercepts, 0.975)),
        "slope_ci_lo": float(np.nanquantile(slopes, 0.025)),
        "slope_ci_hi": float(np.nanquantile(slopes, 0.975)),
    }


def _bland_altman(log_reference: np.ndarray, log_model: np.ndarray) -> dict[str, float]:
    log_ratio = log_reference - log_model
    mean = float(np.mean(log_ratio))
    standard_deviation = float(np.std(log_ratio, ddof=1))
    return {
        "mean_log_ratio": mean,
        "sd_log_ratio": standard_deviation,
        "mean_multiplicative_bias": float(np.exp(mean)),
        "lower_95_limit": float(np.exp(mean - 1.96 * standard_deviation)),
        "upper_95_limit": float(np.exp(mean + 1.96 * standard_deviation)),
    }


def _log_error(log_reference: np.ndarray, log_model: np.ndarray) -> dict[str, float]:
    error = log_model - log_reference
    absolute_error = np.abs(error)
    rmse = float(np.sqrt(np.mean(error**2)))
    return {
        "mean_log_error": float(np.mean(error)),
        "median_log_error": float(np.median(error)),
        "mean_abs_log_error": float(np.mean(absolute_error)),
        "median_abs_log_error": float(np.median(absolute_error)),
        "rmse_log": rmse,
        "typical_error_factor": float(np.exp(np.median(absolute_error))),
        "rmse_error_factor": float(np.exp(rmse)),
    }


def _concordance_correlation(x: np.ndarray, y: np.ndarray) -> float:
    variance_x = float(np.var(x, ddof=1))
    variance_y = float(np.var(y, ddof=1))
    covariance = float(np.cov(x, y, ddof=1)[0, 1])
    return float(2 * covariance / (variance_x + variance_y + (float(np.mean(x)) - float(np.mean(y))) ** 2))


def _weighted_kappa(reference: pd.Series, model: pd.Series) -> dict[str, float]:
    reference_codes = pd.Categorical(reference, categories=QUALITATIVE_BANDS, ordered=True).codes
    model_codes = pd.Categorical(model, categories=QUALITATIVE_BANDS, ordered=True).codes
    valid = (reference_codes >= 0) & (model_codes >= 0)
    table = confusion_matrix(reference_codes[valid], model_codes[valid], labels=np.arange(len(QUALITATIVE_BANDS)))
    result = cohens_kappa(table, wt="quadratic")
    kappa = float(result.kappa)
    if hasattr(result, "se_kappa"):
        standard_error = float(result.se_kappa)
    elif hasattr(result, "std_kappa"):
        standard_error = float(result.std_kappa)
    elif hasattr(result, "var_kappa"):
        standard_error = float(math.sqrt(result.var_kappa))
    else:
        raise AttributeError("statsmodels kappa result did not expose a standard error")
    z = float(stats.norm.ppf(0.975))
    return {
        "n": int(valid.sum()),
        "weighted_kappa": kappa,
        "weighted_kappa_ci_low": max(-1.0, kappa - z * standard_error),
        "weighted_kappa_ci_high": min(1.0, kappa + z * standard_error),
        "exact_match_pct": float(np.mean(reference_codes[valid] == model_codes[valid]) * 100),
        "within_1_tier_pct": float(np.mean(np.abs(reference_codes[valid] - model_codes[valid]) <= 1) * 100),
    }


def _pitman_morgan(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    valid = np.isfinite(x) & np.isfinite(y)
    x = x[valid]
    y = y[valid]
    summed = x + y
    difference = x - y
    correlation = float(np.corrcoef(summed, difference)[0, 1])
    statistic = correlation * np.sqrt(len(x) - 2) / np.sqrt(1 - correlation**2)
    return float(statistic), float(2 * stats.t.sf(abs(statistic), len(x) - 2))


def _bradley_blackwood(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    valid = np.isfinite(x) & np.isfinite(y)
    x = x[valid]
    y = y[valid]
    n = len(x)
    difference = y - x
    average = (y + x) / 2
    design = np.column_stack((np.ones(n), average))
    coefficients = np.linalg.lstsq(design, difference, rcond=None)[0]
    residual_sum_squares = float(np.sum((difference - design @ coefficients) ** 2))
    null_sum_squares = float(np.sum(difference**2))
    statistic = ((null_sum_squares - residual_sum_squares) / 2) / (residual_sum_squares / (n - 2))
    return float(statistic), float(stats.f.sf(statistic, 2, n - 2))


def _pairwise_model_comparisons(data: pd.DataFrame) -> pd.DataFrame:
    log_reference = np.log(data["lr_reported"].to_numpy(dtype=float))
    notebook_order = (
        ("GPT-4o", "gpt-4o-2024-11-20", "lr_gpt-4o-2024-11-20"),
        ("o3", "o3-2025-04-16", "lr_o3-2025-04-16"),
        ("GPT-5", "gpt-5", "lr_gpt-5"),
    )
    error_vectors = [
        (
            display_name,
            api_model,
            log_reference - np.log(data[model_column].to_numpy(dtype=float)),
        )
        for display_name, api_model, model_column in notebook_order
    ]
    rows = []
    for (display_a, api_a, error_a), (display_b, api_b, error_b) in itertools.combinations(error_vectors, 2):
        valid = np.isfinite(error_a) & np.isfinite(error_b)
        x = error_a[valid]
        y = error_b[valid]
        n = len(x)
        paired_difference = x - y
        bias_ln = float(np.mean(paired_difference))
        standard_error = float(np.std(paired_difference, ddof=1) / np.sqrt(n))
        t_statistic = bias_ln / standard_error
        p_t = float(2 * stats.t.sf(abs(t_statistic), n - 1))
        ci_low, ci_high = stats.t.interval(0.95, n - 1, loc=bias_ln, scale=standard_error)
        pitman_morgan_t, pitman_morgan_p = _pitman_morgan(x, y)
        bradley_blackwood_f, bradley_blackwood_p = _bradley_blackwood(x, y)
        rows.append(
            {
                "comparison": f"{display_a} vs {display_b}",
                "display_name_a": display_a,
                "api_model_a": api_a,
                "display_name_b": display_b,
                "api_model_b": api_b,
                "n": n,
                "bias_ln": bias_ln,
                "bias_ratio": float(np.exp(bias_ln)),
                "ci95_ln_low": float(ci_low),
                "ci95_ln_high": float(ci_high),
                "ci95_ratio_low": float(np.exp(ci_low)),
                "ci95_ratio_high": float(np.exp(ci_high)),
                "t_stat": float(t_statistic),
                "p_t": p_t,
                "loa_width_a": float(1.96 * 2 * np.std(x, ddof=1)),
                "loa_width_b": float(1.96 * 2 * np.std(y, ddof=1)),
                "pitman_morgan_t": pitman_morgan_t,
                "pitman_morgan_p": pitman_morgan_p,
                "bradley_blackwood_f": bradley_blackwood_f,
                "bradley_blackwood_p": bradley_blackwood_p,
            }
        )
    return pd.DataFrame(rows)


def _summarize_zone(
    data: pd.DataFrame,
    mask: pd.Series,
    zone: str,
    range_description: str,
    interpretation: str,
    display_name: str,
    api_model: str,
    model_column: str,
) -> dict[str, object]:
    reference = np.log(data.loc[mask, "lr_reported"].to_numpy(dtype=float))
    model = np.log(data.loc[mask, model_column].to_numpy(dtype=float))
    calibration = _ols(reference, model)
    pearson = stats.pearsonr(reference, model)
    spearman = stats.spearmanr(reference, model)
    return {
        "zone": zone,
        "reported_lr_range": range_description,
        "display_name": display_name,
        "api_model": api_model,
        "n": len(reference),
        **calibration,
        "pearson_r": float(pearson.statistic),
        "pearson_p": float(pearson.pvalue),
        "spearman_rho": float(spearman.statistic),
        "spearman_p": float(spearman.pvalue),
        **_log_error(reference, model),
        **_bland_altman(reference, model),
        "ccc_log": _concordance_correlation(reference, model),
        "interpretation": interpretation,
    }


def _laboratory_flags(data: pd.DataFrame) -> dict:
    keyword_pattern = re.compile(
        r"\b(?:"
        r"bnp|nt[- ]?probnp|troponin|d[- ]?dimer|rpr|rapid plasma reagin|"
        r"esr|erythrocyte sedimentation|c reactive protein|crp|"
        r"hemoglobin|glucose|wbc|white blood|platelet|creatinine|lactate|"
        r"bilirubin|aminotransferase|alt|ast|lipase|amylase|urinalysis|"
        r"proteinuria|ketone|hba1c|serum|plasma|blood|urine|assay|culture|"
        r"antibody|antigen|titer|mg/dl|pg/ml|ng/ml|mm/h|mm/hr|u/l|iu/l|g/dl"
        r")\b|%",
        flags=re.IGNORECASE,
    )
    threshold_pattern = re.compile(
        r"(?:[<>]=?|>=|<=|≥|≤|\bat least\b|\babove\b|\bbelow\b)\s*\d|\d+(?:\.\d+)?",
        flags=re.IGNORECASE,
    )
    unit_pattern = re.compile(
        r"(?:mg\s*/\s*dL|pg\s*/\s*mL|ng\s*/\s*mL|mm\s*/\s*h|mm\s*/\s*hr|"
        r"u\s*/\s*L|iu\s*/\s*L|g\s*/\s*dL|mmol\s*/\s*L|cells?\s*/\s*(?:uL|µL|μL)|%)",
        flags=re.IGNORECASE,
    )
    finding = data["finding_curated"].fillna("").astype(str)
    feature_type = data["feature_type_raw"].fillna("").astype(str)
    lab_like = feature_type.str.contains("test", case=False, na=False) & finding.str.contains(keyword_pattern, na=False)
    candidates = data.loc[lab_like].copy()
    candidates["abs_log_error"] = np.abs(
        np.log(candidates["lr_gpt-5"].astype(float)) - np.log(candidates["lr_reported"].astype(float))
    )
    candidates = candidates.sort_values("abs_log_error", ascending=False, kind="mergesort").head(10)
    threshold_present = candidates["finding_curated"].astype(str).str.contains(threshold_pattern, na=False)
    unit_present = candidates["finding_curated"].astype(str).str.contains(unit_pattern, na=False)
    extreme = (candidates["lr_reported"] < 0.2) | (candidates["lr_reported"] > 5.0)
    return {
        "schema_version": 1,
        "model": "gpt-5",
        "selection": "ten largest absolute log errors among lab-like test-result findings",
        "n": 10,
        "threshold_present": int(threshold_present.sum()),
        "unit_present": int(unit_present.sum()),
        "extreme_reported_lr": int(extreme.sum()),
        "top_10_row_ids": candidates["row_id"].tolist(),
    }


def _coverage_intervals(data: pd.DataFrame, log_reference: np.ndarray) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for display_name, api_model, model_column in MODEL_SPECS:
        errors = log_reference - np.log(data[model_column].to_numpy(dtype=float))
        n = len(errors)
        mean_log = float(np.mean(errors))
        standard_deviation = float(np.std(errors, ddof=1))
        t_multiplier = float(stats.t.ppf(0.975, n - 1))
        for coverage in (0.50, 0.75, 0.90, 0.95, 0.99):
            z_multiplier = float(stats.norm.ppf(0.5 + coverage / 2))
            lower_log = mean_log - z_multiplier * standard_deviation
            upper_log = mean_log + z_multiplier * standard_deviation
            limit_standard_error = standard_deviation * np.sqrt(1 / n + z_multiplier**2 / (2 * (n - 1)))
            rows.append(
                {
                    "display_name": display_name,
                    "api_model": api_model,
                    "n": n,
                    "coverage_percent": int(coverage * 100),
                    "lower": float(np.exp(lower_log)),
                    "upper": float(np.exp(upper_log)),
                    "lower_ci_low": float(np.exp(lower_log - t_multiplier * limit_standard_error)),
                    "lower_ci_high": float(np.exp(lower_log + t_multiplier * limit_standard_error)),
                    "upper_ci_low": float(np.exp(upper_log - t_multiplier * limit_standard_error)),
                    "upper_ci_high": float(np.exp(upper_log + t_multiplier * limit_standard_error)),
                }
            )
    return pd.DataFrame(rows)


def _evidence_direction_tests(data: pd.DataFrame, log_reference: np.ndarray) -> pd.DataFrame:
    negative = log_reference < 0
    positive = log_reference > 0
    rows: list[dict[str, object]] = []
    for display_name, api_model, model_column in MODEL_SPECS:
        errors = log_reference - np.log(data[model_column].to_numpy(dtype=float))
        negative_errors = errors[negative & np.isfinite(errors)]
        positive_errors = errors[positive & np.isfinite(errors)]
        t_result = stats.ttest_ind(negative_errors, positive_errors, equal_var=False, nan_policy="omit")
        levene_result = stats.levene(negative_errors, positive_errors, center="median")
        rows.append(
            {
                "display_name": display_name,
                "api_model": api_model,
                "n_negative": len(negative_errors),
                "n_positive": len(positive_errors),
                "negative_mean_bias_ratio": float(np.exp(np.mean(negative_errors))),
                "positive_mean_bias_ratio": float(np.exp(np.mean(positive_errors))),
                "welch_t": float(t_result.statistic),
                "welch_p": float(t_result.pvalue),
                "levene_brown_forsythe_f": float(levene_result.statistic),
                "levene_brown_forsythe_p": float(levene_result.pvalue),
            }
        )
    return pd.DataFrame(rows)


def compute_reference_results(input_csv: Path, output_dir: Path) -> dict[str, Path]:
    """Compute all reference files and return a mapping of logical names to paths."""
    input_csv = input_csv.resolve()
    output_dir = output_dir.resolve()
    data = pd.read_csv(input_csv)
    required = {
        "row_id",
        "condition_full",
        "finding_curated",
        "feature_type_raw",
        "reported_qualitative_band",
        "lr_reported",
        *(model_column for _, _, model_column in MODEL_SPECS),
    }
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"Canonical input is missing required columns: {missing}")
    if len(data) != 700 or data["condition_full"].nunique() != 30:
        raise ValueError("Reference input must contain 700 rows and 30 full conditions")
    numeric = data[["lr_reported", *(model_column for _, _, model_column in MODEL_SPECS)]].to_numpy(dtype=float)
    if not np.isfinite(numeric).all() or not (numeric > 0).all():
        raise ValueError("All reported and manuscript-model LRs must be positive and finite")

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "main_metrics": output_dir / "main_metrics.json",
        "category_counts": output_dir / "category_counts.csv",
        "feature_type_counts": output_dir / "feature_type_counts.csv",
        "agreement_metrics": output_dir / "agreement_metrics.csv",
        "pairwise_model_comparisons": output_dir / "pairwise_model_comparisons.csv",
        "coverage_intervals": output_dir / "coverage_intervals.csv",
        "evidence_direction_tests": output_dir / "evidence_direction_tests.csv",
        "calibration_metrics": output_dir / "calibration_metrics.csv",
        "reliability_metrics": output_dir / "reliability_metrics.csv",
        "kappa_metrics": output_dir / "kappa_metrics.csv",
        "reliability_zone_metrics": output_dir / "reliability_zone_metrics.csv",
        "laboratory_discrepancy_flags": output_dir / "laboratory_discrepancy_flags.json",
        "readme": output_dir / "README.md",
    }

    reported = data["lr_reported"].to_numpy(dtype=float)
    _write_json(
        {
            "schema_version": 1,
            "source": "data/curated/diagnostic_lrs_manuscript_v1.csv",
            "dataset": {
                "rows": len(data),
                "conditions": int(data["condition_full"].nunique()),
                "reported_lr": {
                    "minimum": float(np.min(reported)),
                    "maximum": float(np.max(reported)),
                    "percentile_25": float(np.percentile(reported, 25)),
                    "median": float(np.percentile(reported, 50)),
                    "percentile_75": float(np.percentile(reported, 75)),
                    "geometric_mean": float(np.exp(np.mean(np.log(reported)))),
                },
            },
            "floating_point_tolerance": 0.001,
        },
        paths["main_metrics"],
    )

    category_counts = (
        data["reported_qualitative_band"]
        .value_counts()
        .reindex(QUALITATIVE_BANDS, fill_value=0)
        .rename_axis("reported_qualitative_band")
        .reset_index(name="count")
    )
    category_counts["percent"] = category_counts["count"] / len(data) * 100
    _write_csv(category_counts, paths["category_counts"])

    feature_specs = (
        ("Signs/Symptoms", "is_sign_or_symptom"),
        ("History", "is_history"),
        ("Test results", "is_test_result"),
        ("Imaging", "is_imaging"),
        ("Diagnosis/diagnostic adjudication", "is_diagnostic_adjudication"),
    )
    feature_counts = pd.DataFrame(
        [
            {
                "feature_type": label,
                "indicator_column": column,
                "count": int(data[column].sum()),
                "percent": float(data[column].sum() / len(data) * 100),
            }
            for label, column in feature_specs
        ]
    )
    _write_csv(feature_counts, paths["feature_type_counts"])

    log_reference = np.log(reported)
    agreement_rows = []
    for display_name, api_model, model_column in MODEL_SPECS:
        log_model = np.log(data[model_column].to_numpy(dtype=float))
        agreement_rows.append(
            {
                "display_name": display_name,
                "api_model": api_model,
                "n": len(data),
                **_bland_altman(log_reference, log_model),
                **_log_error(log_reference, log_model),
            }
        )
    _write_csv(pd.DataFrame(agreement_rows), paths["agreement_metrics"])
    _write_csv(_pairwise_model_comparisons(data), paths["pairwise_model_comparisons"])
    _write_csv(_coverage_intervals(data, log_reference), paths["coverage_intervals"])
    _write_csv(_evidence_direction_tests(data, log_reference), paths["evidence_direction_tests"])

    calibration_rng = np.random.default_rng(20260407)
    calibration_rows = []
    for display_name, api_model, model_column in MODEL_SPECS:
        log_model = np.log(data[model_column].to_numpy(dtype=float))
        metrics = _bootstrap_primary_calibration(log_reference, log_model, calibration_rng)
        calibration_rows.append(
            {
                "display_name": display_name,
                "api_model": api_model,
                "n": len(data),
                "intercept": metrics["intercept"],
                "slope": metrics["slope"],
                "slope_ci_lo": metrics["cs_ci_lo"],
                "slope_ci_hi": metrics["cs_ci_hi"],
                "r_squared": metrics["r_squared"],
                "oe": metrics["oe"],
                "oe_ci_lo": metrics["oe_ci_lo"],
                "oe_ci_hi": metrics["oe_ci_hi"],
                "cs": metrics["cs"],
                "cs_ci_lo": metrics["cs_ci_lo"],
                "cs_ci_hi": metrics["cs_ci_hi"],
                "citl": metrics["citl"],
                "citl_ci_lo": metrics["citl_ci_lo"],
                "citl_ci_hi": metrics["citl_ci_hi"],
            }
        )
    _write_csv(pd.DataFrame(calibration_rows), paths["calibration_metrics"])

    reliability_rng = np.random.default_rng(20260407)
    reliability_rows = []
    for display_name, api_model, model_column in MODEL_SPECS:
        log_model = np.log(data[model_column].to_numpy(dtype=float))
        metrics = _bootstrap_reliability(log_model, log_reference, reliability_rng)
        reliability_rows.append(
            {
                "display_name": display_name,
                "api_model": api_model,
                "n": len(data),
                "reliability_intercept": metrics["intercept"],
                "reliability_intercept_ci_lo": metrics["intercept_ci_lo"],
                "reliability_intercept_ci_hi": metrics["intercept_ci_hi"],
                "reliability_slope": metrics["slope"],
                "reliability_slope_ci_lo": metrics["slope_ci_lo"],
                "reliability_slope_ci_hi": metrics["slope_ci_hi"],
                "reliability_r_squared": metrics["r_squared"],
            }
        )
    _write_csv(pd.DataFrame(reliability_rows), paths["reliability_metrics"])

    kappa_rows = []
    for display_name, api_model, model_column in MODEL_SPECS:
        model_bands = data[model_column].map(
            lambda value: (
                "Strong Negative"
                if value <= 0.1
                else "Moderate Negative"
                if value <= 0.2
                else "Weak Negative"
                if value < 0.5
                else "Negligible"
                if value < 2
                else "Weak Positive"
                if value < 5
                else "Moderate Positive"
                if value < 10
                else "Strong Positive"
            )
        )
        kappa_rows.append(
            {
                "display_name": display_name,
                "api_model": api_model,
                **_weighted_kappa(data["reported_qualitative_band"], model_bands),
            }
        )
    _write_csv(pd.DataFrame(kappa_rows), paths["kappa_metrics"])

    central = data["lr_reported"].between(0.2, 5.0, inclusive="both")
    zone_specs = (
        (
            "Central reliability zone",
            "0.2 <= reported LR <= 5.0",
            central,
            "Central range where calibration curves suggest greatest reliability.",
        ),
        (
            "Extreme LR zone",
            "reported LR < 0.2 or reported LR > 5.0",
            ~central,
            "Extreme range where estimates may compress toward neutrality and should be interpreted cautiously.",
        ),
    )
    zone_rows = []
    for zone, range_description, mask, interpretation in zone_specs:
        for display_name, api_model, model_column in MODEL_SPECS:
            zone_rows.append(
                _summarize_zone(
                    data,
                    mask,
                    zone,
                    range_description,
                    interpretation,
                    display_name,
                    api_model,
                    model_column,
                )
            )
    _write_csv(pd.DataFrame(zone_rows), paths["reliability_zone_metrics"])

    _write_json(_laboratory_flags(data), paths["laboratory_discrepancy_flags"])
    paths["readme"].write_text(REFERENCE_README, encoding="utf-8")
    return paths


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/curated/diagnostic_lrs_manuscript_v1.csv"),
    )
    parser.add_argument("--output", type=Path, default=Path("results/reference"))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    for name, path in sorted(compute_reference_results(args.input, args.output).items()):
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
