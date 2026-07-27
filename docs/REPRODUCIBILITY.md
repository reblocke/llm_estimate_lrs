# Reproducing the accepted analysis

This workflow supports “Large language models generate diagnostic likelihood ratios with low mean bias but wide dispersion” ([DOI: 10.1038/s41598-026-61766-2](https://doi.org/10.1038/s41598-026-61766-2)). Published online in *Scientific Reports* on 11 July 2026 as a citable, unedited early-access article; publisher production editing remains ongoing.

## Definition

Reproduction in this repository means recalculating the accepted-paper numerical results from the frozen local dataset and model outputs, using the locked environment and accepted analysis contract. It is deliberately offline: no model query, web scrape, or missing-value regeneration is permitted.

A live model call is a new replication and follows [Replication](REPLICATION.md).

## Canonical inputs

| Input | Role |
|---|---|
| `NNT_LRs_08-26-2025.xlsx` | Immutable accepted-paper analysis workbook |
| `nnt_lrs_with_estimated.xlsx` | Immutable per-condition workbook and full-label context |
| `data/curated/diagnostic_lrs_manuscript_v1.csv` | Deterministic 700-row analysis export |
| `data/model_outputs/manuscript_model_outputs_v1.csv` | Frozen three-model output table |
| `data/model_outputs/threshold_perturbation_v1/` | Frozen threshold sensitivity evidence |
| `config/analysis_categories_v1.json` | Accepted qualitative LR bands |
| `config/manuscript_models_v1.json` | Accepted three-model scope and settings |
| `prompts/main_estimator_v1.json` | Exact historical main-estimator prompt |
| `prompts/threshold_perturbation_v1.json` | Exact historical sensitivity prompt |
| `manifests/manuscript_run_v1.json` | Input, provenance, and expected-artifact inventory |
| `results/reference/` | Frozen numerical contract |

The canonical CSV is additive. It does not replace or modify either workbook.
The advancing maintenance tree also carries a draft
[`ANALYSIS_SPEC.md`](../ANALYSIS_SPEC.md) and machine-readable source,
variable, rights, and output registries under [`metadata/`](../metadata/).
These are post-release governance records and do not alter the tag-scoped v1
manifest.

## Environment and commands

Use Python 3.11 and the locked `uv` environment:

```bash
pip install uv
make setup
make kernel
make verify-checksums
make validate-metadata
make validate-data
make reproduce
make test
```

The optional project kernel is installed inside the locked environment as `Python (llm-estimate-lrs v1)`. It prevents notebook execution under an unrelated system or Conda interpreter.

`make setup` is the explicit provisioning boundary and may download missing
locked packages. The integrity and reproduction targets use the provisioned
root and CFF environments with offline, no-sync execution; if either
environment is absent, they fail with setup instructions instead of creating
it.

`make reproduce` invokes the offline reproduction entry point and writes only to `results/runs/reproduction/`. That directory is generated and ignored. A new reproduction may replace that dedicated output directory, but it cannot modify the tracked inputs or `results/reference/`.

## Expected outputs

The reproduction output contains recalculated machine-readable results and a run summary. Compare it with:

- `results/reference/main_metrics.json`
- `results/reference/category_counts.csv`
- `results/reference/feature_type_counts.csv`
- `results/reference/agreement_metrics.csv`
- `results/reference/pairwise_model_comparisons.csv`
- `results/reference/coverage_intervals.csv`
- `results/reference/evidence_direction_tests.csv`
- `results/reference/calibration_metrics.csv`
- `results/reference/reliability_metrics.csv`
- `results/reference/kappa_metrics.csv`
- `results/reference/reliability_zone_metrics.csv`
- `results/reference/laboratory_discrepancy_flags.json`

The contract includes 700 rows, 30 conditions, 2,100 positive finite manuscript-model outputs, 700 one-to-one workbook matches, and the expected metrics listed in [Accepted-paper crosswalk](ACCEPTED_PAPER_CROSSWALK.md).

## Integrity checks

`make verify-checksums` verifies files listed in `checksums/SHA256SUMS`. The source workbook hashes are:

- `NNT_LRs_08-26-2025.xlsx`: `644f0558328a8f04f460a5ebfa2fc04e6d3571f655d084ea076488c7ba17da89`
- `nnt_lrs_with_estimated.xlsx`: `c375229a27f0854957f6b8963ece145e94d00e4fa75e7e2756e5d130f6f7110d`

The release validator also checks row order, stable IDs, crosswalk completeness, model scope, finite positive values, prompt hashes, threshold artifact hashes, documentation metadata, and numerical tolerances. `make validate-metadata` separately checks artifact hashes, exact public-CSV column coverage, rights classes, and accepted-output/crosswalk traceability.

## Offline guarantee

Reproduction must succeed with `OPENAI_API_KEY` absent. The offline entry point blocks socket access and must fail if any code attempts a network request. It does not instantiate an OpenAI client, execute scraper stages, or fall back to live calls when an artifact is missing.

An absent or mismatched frozen artifact is an integrity failure. The remedy is to recover or verify the artifact, not regenerate it from a hosted service.

## Diagnosing failures

1. Run `uv lock --check` to confirm the lockfile matches project metadata.
2. Run `make verify-checksums` to identify changed or missing frozen files.
3. Run `make validate-metadata` for scientific and registry-contract diagnostics.
4. Run `make validate-data` for row-level, model-scope, and crosswalk diagnostics.
5. Run `uv run --offline --no-sync pytest -q` to see the first failed contract.
6. Remove only the ignored `results/runs/reproduction/` directory and rerun reproduction if the failure is confined to generated output.
7. Confirm `python --version` through
   `uv run --offline --no-sync python --version`; it should use Python 3.11.

Do not edit a frozen input to make a test pass. Unexpected differences should be reported with the failing command, file hash, environment details, and full error message.
