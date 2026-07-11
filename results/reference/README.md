# Frozen reference results

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
