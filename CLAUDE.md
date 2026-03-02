# Project Context

Estimate diagnostic likelihood ratios (LRs) with large language models (LLMs) and evaluate agreement with literature-reported LRs using multiplicative Bland-Altman analysis and ordinal agreement metrics.

# Repository Layout

```
.
├── lr_scraper_estimator.ipynb   # builds prompts, calls OpenAI models, writes filled spreadsheet
├── data_analysis.ipynb          # bias/LoA, coverage, subgroup tests, Cohen's kappa, figures/tables
├── pyproject.toml               # project metadata and dependencies (uv)
├── uv.lock                      # pinned dependency versions
├── .env.example                 # template for secrets
├── .gitignore
├── Paper/                       # manuscript drafts and submissions (.docx)
├── Past Runs/                   # historical output spreadsheets
└── README.md
```

# Environment Setup

- Python >=3.11, managed with **uv**
- `uv sync` to install all pinned dependencies
- `.env` file at repo root with `OPENAI_API_KEY=sk-...` (see `.env.example`)

# Key Files

- `lr_scraper_estimator.ipynb` — LR estimation notebook (API calls to OpenAI)
- `data_analysis.ipynb` — statistical analysis and publication-ready figures
- `pyproject.toml` — dependencies and project metadata
- `uv.lock` — locked dependency versions for reproducibility

# Customization Points

## In `lr_scraper_estimator.ipynb`
- **I/O paths**: `INPUT_FILE`, `OUTPUT_FILE` (Excel paths).
- **Models**: `MODELS` (e.g., `"gpt-5"`, `"gpt-5-mini"`, `"gpt-4o-2024-11-20"`, `"o3-2025-04-16"`).
- **Model flags**: `MODEL_CAPABILITIES` (reasoning vs non-reasoning; verbosity support).
- **Prompt scaffolding**: `SYSTEM_CORE`, `DEFINITION`, `BANDS`; few-shot exemplars `FEW_SHOT_RICH` / `FEW_SHOT_MIN`.
- **API behavior**: set reasoning effort for reasoning models (e.g., `"medium"`).

## In `data_analysis.ipynb`
- **Output dirs**: `WORKING_DIR`; auto-dated `OUTPUT_DIR = results/YYYY-MM-DD` is created if missing.
- **Model columns**: choose which LR columns to analyze and plot.
- **Ordinal bands**: `CATS` and `LR_BANDS` used for kappa and plots.
- **Plot style**: the notebook sets Matplotlib to **DejaVu Sans** to avoid Unicode glyph warnings.

# Running Non-Interactively

```bash
uv run papermill lr_scraper_estimator.ipynb out/scraper_run.ipynb
uv run papermill data_analysis.ipynb      out/analysis_run.ipynb
```

# Troubleshooting

- **OpenAI error**: ensure `OPENAI_API_KEY` is set and you have access to the specified model IDs.
- **Glyph warnings**: keep the default DejaVu Sans settings in the analysis notebook or escape math as `$\leq$`/`$\geq$`.
- **Missing packages**: run `uv sync` to install exact dependencies from `pyproject.toml`/`uv.lock`.

# Testing Changes

1. Run `uv sync` to ensure dependencies are up to date
2. Run `uv run papermill lr_scraper_estimator.ipynb out/scraper_run.ipynb`
3. Run `uv run papermill data_analysis.ipynb out/analysis_run.ipynb`
4. Verify output files are generated without errors
