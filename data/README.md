# Frozen release data

This directory contains machine-readable exports supporting the published
early-access article. `NNT_LRs_08-26-2025.xlsx` remains the numerical source of
truth and
`nnt_lrs_with_estimated.xlsx` supplies the per-condition worksheet context and
full condition labels. Neither workbook is modified by the release builders.

## Files

- `curated/diagnostic_lrs_manuscript_v1.csv`: 700 accepted-workbook rows in
  original order, with stable row IDs, full condition labels, overlapping
  feature indicators, and qualitative LR bands.
- `model_outputs/manuscript_model_outputs_v1.csv`: the frozen 700 by 3 outputs
  for the three models analyzed in the published early-access article.
- `model_outputs/auxiliary_gpt-4.1_outputs_v1.csv`: preserved historical GPT-4.1
  values that were not analyzed in the published early-access article.
- `model_outputs/manuscript_query_run_v1.csv`: recoverable run configuration;
  unavailable response metadata is left blank.
- `model_outputs/threshold_perturbation_v1/`: byte-identical copies of the five
  accepted 16 May 2026 threshold-sensitivity artifacts.
- `provenance/source_crosswalk_v1.csv`: strict occurrence-index crosswalk from
  every Master-sheet row to exactly one per-condition worksheet row.
- `provenance/curation_log_v1.csv`: intentionally empty apart from its header
  because row-level historical curation rationales were not recovered.
- `provenance/provenance_gaps_v1.csv`: explicit unavailable provenance fields.

`curation_status=accepted_workbook_value` identifies a frozen value in the
accepted analysis workbook; it does not assert that a recoverable row-level
curation rationale exists.

## Feature indicators

The five feature indicators reproduce the accepted string-matching rules on
`Feature Type`. They overlap by design, so their memberships sum to more than
700.

## Provenance and reuse

The repository's MIT license applies to original software, not automatically to
all material in this directory. The exports combine literature-derived/TheNNT
comparison values, author-created curation and feature labels, and
author-generated model outputs. Users must evaluate the source terms and the
intended use of each component. No publisher-formatted article content is
included here.
