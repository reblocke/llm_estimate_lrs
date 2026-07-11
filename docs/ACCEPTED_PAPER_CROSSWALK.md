# Accepted-paper result crosswalk

This crosswalk maps the published early-access article’s numerical claims to frozen inputs, executable analysis, and machine-readable expected results. `make reproduce` recalculates the offline contract; `make test` compares it with `results/reference/`.

| Result | Frozen input | Code | Reference output | Expected contract |
|---|---|---|---|---|
| Dataset description | Canonical CSV; source workbooks | `scripts/build_release_dataset.py`; `data_analysis.ipynb` | `main_metrics.json` | 700 rows; 30 conditions; reported LR 0.01 to about 145.89; median 1.0 |
| LR category distribution | Canonical CSV; category config | `scripts/compute_reference_results.py`; `data_analysis.ipynb` | `category_counts.csv` | 17, 22, 60, 400, 120, 52, 29 in configured order |
| Feature-type distribution | Canonical CSV | `scripts/compute_reference_results.py`; `data_analysis.ipynb` | `feature_type_counts.csv` | 416 signs/symptoms; 134 history; 110 tests; 57 imaging; 8 adjudication memberships |
| Bland–Altman agreement | Frozen three-model outputs | `data_analysis.ipynb`; reference script | `agreement_metrics.csv` | Reported/model mean ratios 1.018, 0.987, 0.988 for GPT-4o, o3, GPT-5 |
| Pairwise bias and dispersion comparisons | Frozen three-model outputs | `data_analysis.ipynb`; reference script | `pairwise_model_comparisons.csv` | Paired bias, Pitman–Morgan variance, and Bradley–Blackwood statistics reproduce the accepted notebook formulas |
| Coverage intervals | Frozen three-model outputs | `data_analysis.ipynb`; reference script | `coverage_intervals.csv` | 50%, 75%, 90%, 95%, and 99% multiplicative intervals and confidence limits |
| Evidence-direction comparisons | Frozen three-model outputs | `data_analysis.ipynb`; reference script | `evidence_direction_tests.csv` | LR-below-one versus LR-above-one Welch and Brown–Forsythe/Levene tests |
| Forward calibration | Frozen three-model outputs | `data_analysis.ipynb`; reference script | `calibration_metrics.csv` | Accepted intercepts, slopes, confidence intervals, and R² values |
| Inverse reliability calibration | Frozen three-model outputs | `data_analysis.ipynb`; reference script | `reliability_metrics.csv` | Slopes 0.734, 0.763, 0.877 and R² 0.655, 0.645, 0.675 |
| Qualitative agreement | Canonical CSV; category config | `data_analysis.ipynb`; reference script | `kappa_metrics.csv` | Quadratically weighted kappa about 0.734, 0.745, 0.775 |
| Central vs extreme reliability zones | Canonical CSV | `supplementary_analyses.ipynb`; reference script | `reliability_zone_metrics.csv` | 585 central and 115 extreme rows per model; accepted error/calibration metrics |
| Laboratory-discrepancy table | Canonical CSV | `supplementary_analyses.ipynb`; reference script | `laboratory_discrepancy_flags.json` | Top-ten GPT-5 table flags: 5 threshold, 3 unit, 6 extreme reported LR |
| Threshold perturbation sensitivity | Frozen 16 May 2026 threshold files | `threshold_perturbation_sensitivity_analysis.ipynb` in frozen-analysis mode | `data/model_outputs/threshold_perturbation_v1/` | 15 successful rows across 5 case families; historical summary preserved byte-for-byte |

## Agreement values

The Bland–Altman difference is calculated on log-transformed LRs and reported after exponentiation as the literature-reported/model-generated ratio.

| Model | Mean multiplicative bias | Lower 95% limit | Upper 95% limit |
|---|---:|---:|---:|
| GPT-4o | 1.018 | 0.229 | 4.527 |
| o3 | 0.987 | 0.227 | 4.281 |
| GPT-5 | 0.988 | 0.264 | 3.703 |

Stored unrounded calculations use tolerance `1e-3`; display comparisons use tolerance `0.01`.

## Evidence-direction reporting note

The accepted author-manuscript sentence lists the o3 evidence-direction ratios as
0.95x for negative evidence and 1.03x for positive evidence. The frozen executable
analysis and `evidence_direction_tests.csv` assign 1.0326838754 to negative evidence
and 0.9504718609 to positive evidence (Welch P = 0.1454697). Thus, the rounded pair
and inference are unchanged, but the stratum order in that sentence is reversed
relative to the executable analysis. This release preserves both the submitted
wording and the frozen calculation; it does not silently relabel either artifact.

## Reliability-zone values

The central zone is `0.2 <= LR_reported <= 5.0` and contains 585 rows; the extreme zone contains 115. For GPT-5, expected median absolute log error is approximately 0.182 centrally and 0.588 at the extremes; log-scale RMSE is approximately 0.565 and 1.065, respectively.

## Figures

The accepted figures remain governed by `data_analysis.ipynb` and the submitted artifacts. Release preparation does not regenerate or replace them. Numerical figure inputs are covered by the reference metrics above. A release asset may include a figure only when it is byte-identical to a maintainer-approved submitted artifact.

## Commands

```bash
make verify-checksums
make validate-data
make reproduce
make test
```

No command in this crosswalk requires network access or an API key.
