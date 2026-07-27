# Large language models generate diagnostic likelihood ratios with low mean bias but wide dispersion

[![DOI](https://img.shields.io/badge/DOI-10.1038%2Fs41598--026--61766--2-blue)](https://doi.org/10.1038/s41598-026-61766-2)
[![Latest release](https://img.shields.io/github/v/release/reblocke/llm_estimate_lrs?label=release)](https://github.com/reblocke/llm_estimate_lrs/releases/latest)
[![Offline checks](https://github.com/reblocke/llm_estimate_lrs/actions/workflows/ci.yml/badge.svg)](https://github.com/reblocke/llm_estimate_lrs/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/Code%20license-MIT-yellow.svg)](LICENSE)

> Code and frozen research artifacts supporting the *Scientific Reports* article on large-language-model estimates of diagnostic likelihood ratios.

> **Release status:** [`v1.0.0`](https://github.com/reblocke/llm_estimate_lrs/releases/tag/v1.0.0) is the immutable accepted-paper snapshot. [`v1.1.0`](https://github.com/reblocke/llm_estimate_lrs/releases/tag/v1.1.0) is the current maintenance release; it changes documentation, metadata, and reproducibility tooling without changing any accepted input, output, analysis, figure, or conclusion.

## Article and releases

The article was published online in *Scientific Reports* on 11 July 2026 as an unedited early-access article: [DOI: 10.1038/s41598-026-61766-2](https://doi.org/10.1038/s41598-026-61766-2).

Use `v1.0.0` when citing the exact repository snapshot released with the paper. Use `v1.1.0` for the same frozen scientific record with improved navigation, metadata, validation, and machine-readable guidance; complete citation metadata are in [`CITATION.cff`](CITATION.cff).

## Study at a glance

The study compared 700 literature-reported likelihood ratios (LRs), spanning 30 clinical conditions, with 2,100 estimates from three large language models. Mean multiplicative bias was close to one for all three models, but the wide limits of agreement showed substantial dispersion in individual estimates.

Each literature LR was paired with one estimate per model, yielding a matched three-model comparison. Analyses evaluated multiplicative agreement, calibration, evidence direction, qualitative LR categories, and reliability zones. This design tests how well model estimates track the curated reference set; it does not establish clinical safety or validate current hosted model versions.

The accepted analysis uses these exact historical configurations:

- GPT-4o: `gpt-4o-2024-11-20`, temperature 0.2, rich eight-example set.
- o3: `o3-2025-04-16`, reasoning effort `medium`, minimal two-example set.
- GPT-5: `gpt-5`, reasoning effort `medium`, text verbosity `low`, minimal two-example set.

The GPT-5 alias identifies the accepted historical run and does not guarantee identical behavior from a future hosted model. Historical GPT-4.1 values are retained for context but were not analyzed in the accepted manuscript.

### Selected published results

| Model | Mean reported/model ratio | Lower 95% limit | Upper 95% limit |
|---|---:|---:|---:|
| GPT-4o | 1.018 | 0.229 | 4.527 |
| o3 | 0.987 | 0.227 | 4.281 |
| GPT-5 | 0.988 | 0.264 | 3.703 |

These values summarize agreement on the multiplicative scale. See the [accepted-paper crosswalk](docs/ACCEPTED_PAPER_CROSSWALK.md) for the complete set of frozen results and the documented evidence-direction wording discrepancy.

## Reproduce the paper

Run the following commands from the repository root with Python 3.11:

```bash
pip install uv
uv lock --check
make setup
make reproduce
make test
```

`make setup` may download the locked dependencies. Reproduction and tests then use frozen local artifacts, make no OpenAI API calls or live TheNNT requests, and write generated verification files only under `results/runs/reproduction/`.

See [Reproducibility](docs/REPRODUCIBILITY.md) for platform details, expected outputs, integrity checks, and troubleshooting.

## Paper-to-code map

| Paper component | Primary implementation | Frozen evidence |
|---|---|---|
| Agreement, calibration, evidence direction, and qualitative categories | `data_analysis.ipynb` | `results/reference/` |
| Reliability zones and laboratory-discrepancy review | `supplementary_analyses.ipynb` | `reliability_zone_metrics.csv`; `laboratory_discrepancy_flags.json` |
| Threshold sensitivity | `threshold_perturbation_sensitivity_analysis.ipynb` | `data/model_outputs/threshold_perturbation_v1/` |
| Frozen data, prompts, and model outputs | `data/`; `config/`; `prompts/` | `manifests/manuscript_run_v1.json` |

The detailed [crosswalk](docs/ACCEPTED_PAPER_CROSSWALK.md) maps each published result to its inputs, code, reference output, expected value, and comparison tolerance.

## Repository guide

- **Source workbooks and analysis data:** the two root workbooks and [`data/`](data/) preserve the accepted rows, model outputs, crosswalks, and explicit provenance gaps.
- **Prompts and configuration:** [`prompts/`](prompts/) and [`config/`](config/) preserve the exact historical prompt text, model scope, settings, and LR categories.
- **Accepted notebooks:** `data_analysis.ipynb`, `supplementary_analyses.ipynb`, `threshold_perturbation_sensitivity_analysis.ipynb`, and `lr_scraper_estimator.ipynb` are frozen paper artifacts.
- **Reference results:** [`results/reference/`](results/reference/) contains compact expected numerical outputs used for offline comparisons.
- **Provenance and metadata:** [`manifests/`](manifests/) and [`metadata/`](metadata/) describe source hashes, variables, rights boundaries, accepted outputs, and known gaps.
- **Detailed documentation:** start with [Reproducibility](docs/REPRODUCIBILITY.md), [Data provenance](docs/DATA_PROVENANCE.md), [Replication](docs/REPLICATION.md), and the [accepted-paper crosswalk](docs/ACCEPTED_PAPER_CROSSWALK.md).

## Run a new model replication

A live model rerun is a new experiment, not reproduction of the paper. Hosted model behavior, aliases, and sampling may change, so a new run must use an explicit model list and call ceiling and must write to a new directory.

Review [Replication](docs/REPLICATION.md) before enabling any live request. Replication is never part of the offline reproduction or test paths and cannot overwrite the accepted workbooks, prompts, model outputs, or reference results.

## Provenance, limitations, and reuse

Literature-reported LRs were collected from TheNNT on 1 April 2025, followed by duplicate independent manual validation and reconciliation. Model outputs were generated on 25 August 2025; the canonical CSV adds stable row IDs and recoverable labels without changing accepted values or row order.

Some row-level source URLs, provider response metadata, retry records, SDK details, and curation rationales were not recoverable. Repeated source rows are preserved, feature categories overlap by design, and unavailable provenance is recorded rather than inferred.

The MIT License applies to original repository software only. It does not relicense literature-reported or TheNNT-derived values, provider outputs, or article text.

`llms-full.txt` is a format-only representation of the pre-production author manuscript, not the publisher Version of Record. It is shared separately under [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/); see [Data provenance](docs/DATA_PROVENANCE.md) and the [rights registry](metadata/rights_and_licenses.yml) before reusing repository material.

## Citation

Please cite the article and the exact repository release used. Cite `v1.0.0` for the paper-release snapshot or `v1.1.0` for the maintained reproducibility package; [`CITATION.cff`](CITATION.cff) contains both the article citation and current repository-release metadata.

## Contributing and contact

Contributions should preserve every frozen accepted-paper artifact and result. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before proposing a change, and report reproducibility problems through [GitHub Issues](https://github.com/reblocke/llm_estimate_lrs/issues) without including credentials, restricted material, or private correspondence.

Maintainer: **Brian W. Locke, MD, MSc**
