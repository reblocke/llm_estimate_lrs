# Running a new replication

## Definition

A replication issues new model requests using a versioned prompt and compares the new outputs with the frozen `v1.0.0` record. It does not recreate the historical model responses, and it must not modify any accepted-paper artifact.

Hosted aliases, inference infrastructure, safety behavior, and sampling can change. Differences from the accepted outputs are replication findings, not reproduction failures.

## Prerequisites

1. Install the locked environment with `uv sync --frozen`.
2. Set `OPENAI_API_KEY` in the shell or an untracked `.env` file copied from `.env.example`.
3. Select an experiment, explicit model list, and maximum number of calls.
4. Choose a unique run ID matching `YYYY-MM-DD_<short-description>_<git-short-sha>`.
5. Review the printed call count before confirming execution.

Never commit the API key or print it in logs. The replication runner reads the key only after all local validation and confirmation gates pass.

## Accepted model configuration

The accepted-paper comparison set is:

- `gpt-4o-2024-11-20`: temperature `0.2`, rich 8-example prompt set;
- `o3-2025-04-16`: reasoning effort `medium`, minimal 2-example prompt set;
- `gpt-5`: reasoning effort `medium`, text verbosity `low`, minimal 2-example prompt set.

The `gpt-5` alias is recorded exactly as used historically. It may resolve to different serving behavior in a future run. Other models are exploratory and must be labeled separately from the manuscript model set.

## Guarded command

```bash
SHORT_SHA="$(git rev-parse --short HEAD)"
make replicate \
  RUN_ID="$(date +%F)_model-replication_${SHORT_SHA}" \
  EXPERIMENT="main" \
  MODELS="gpt-4o-2024-11-20 o3-2025-04-16 gpt-5" \
  MAX_CALLS=2100 \
  CONFIRM_LIVE_API=YES
```

The runner must refuse to start when:

- the run ID is absent or malformed;
- the experiment or model list is implicit;
- the calculated calls exceed `MAX_CALLS`;
- confirmation is not exactly `YES`;
- the output directory already exists;
- a target resolves to a frozen workbook, manuscript output, or reference-result path.

## Immutable run layout

New runs are stored outside the accepted-paper release artifacts:

```text
runs/YYYY-MM-DD_<short-description>_<git-short-sha>/
├── run_manifest.json
├── prompt_snapshot.json
├── query_audit.csv
├── raw_outputs.csv
├── analysis_outputs/
└── SHA256SUMS
```

The run manifest records the repository commit, exact model identifiers, inference settings, prompt hash, start time, requested and completed call counts, software environment, and output hashes. The query audit records one row per attempted request without exposing credentials.

Do not resume into an existing directory unless a future audited resume mode explicitly preserves append-only request state. The default is fail-closed, no overwrite.

## Comparing with `v1.0.0`

Keep the new run immutable and compute comparisons into its `analysis_outputs/` directory. Use stable `row_id` values to join against `data/curated/diagnostic_lrs_manuscript_v1.csv`. Report the prompt and model configuration alongside all comparisons.

Never replace:

- `NNT_LRs_08-26-2025.xlsx`;
- `nnt_lrs_with_estimated.xlsx`;
- `data/model_outputs/manuscript_*`;
- `data/model_outputs/threshold_perturbation_v1/`;
- `results/reference/`.

A future principal dataset, prompt, or model set belongs in a new major release rather than an in-place update to `v1.0.0`.
