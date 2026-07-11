# v1.0.0 — Accepted-paper reproducibility release

## Article

**Large language models generate diagnostic likelihood ratios with low mean bias but wide dispersion**

*Scientific Reports*

[https://doi.org/10.1038/s41598-026-61766-2](https://doi.org/10.1038/s41598-026-61766-2)

Published online in *Scientific Reports* on 11 July 2026 as a citable, unedited early-access article; publisher production editing remains ongoing. This `v1.0.0` GitHub release is the versioned reproducibility record supporting the published early-access article.

## Identifiers

- Release identifier: annotated tag `v1.0.0`
- Release commit: the commit referenced by `v1.0.0`; after approval, verify with `git rev-list -n 1 v1.0.0`

## Scope

This release freezes the data, historical prompts, three-model output set, analysis code, Python environment, threshold-perturbation evidence, and expected results supporting the published early-access article. It adds deterministic machine-readable exports, explicit provenance gaps, checksums, offline reproduction, guarded live replication, and automated release validation.

No accepted-paper analysis, model output, statistic, figure, wording, or conclusion was changed.

## Included frozen artifacts

- The two original analysis workbooks and their verified SHA-256 hashes.
- A 700-row canonical CSV with stable row IDs and a one-to-one workbook crosswalk.
- The 2,100 accepted outputs from GPT-4o, o3, and GPT-5.
- Exact historical main-estimator and threshold-perturbation prompt specifications.
- Exact 16 May 2026 threshold-perturbation raw, case, summary, response-table, and narrative files.
- Compact reference metrics for agreement, calibration, reliability, weighted kappa, reliability zones, and laboratory-discrepancy flags.
- A format-only, licensed pre-production author-manuscript text representation.

## Reproduce

```bash
pip install uv
uv sync --frozen
make verify-checksums
make validate-data
make reproduce
make test
```

Reproduction is offline and does not require `OPENAI_API_KEY`. It makes no OpenAI API calls and no live TheNNT requests.

## New replications

Any live API rerun is a new replication. Hosted model behavior can change, so a rerun is not expected to recreate the frozen outputs exactly. Live runs require an explicit run ID, model list, call ceiling, confirmation, and unused output directory. They cannot overwrite release artifacts.

## Known provenance limitations

- Original row-level API response IDs, timestamps, retry records, raw response JSON, and the exact SDK patch version were not recoverable for every manuscript query.
- Some row-level TheNNT URLs and detailed curation rationales were not recorded.
- Repeated source rows are preserved because the historical records do not establish that they are redundant.
- The author-manuscript text predates publisher production editing and is not the Version of Record.

These gaps are recorded in `data/provenance/provenance_gaps_v1.csv` and `manifests/manuscript_run_v1.json`; no missing provenance was inferred.

## Integrity and citation

Repository-file hashes are listed in `checksums/SHA256SUMS`. The GitHub release attestation records the tag commit and pre-attestation asset hashes after the tag is created; the release-asset `SHA256SUMS` covers the complete downloadable asset set, including the attestation.

Please cite both the article and the `v1.0.0` GitHub release. `CITATION.cff` contains the eight-author article citation and repository-release metadata.

## Release status

This is the publication release of the frozen reproducibility record. It does not alter any accepted-paper input, prompt, model output, statistic, figure, wording, or conclusion.
