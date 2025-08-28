# llm_estimate_lrs

Estimate diagnostic likelihood ratios (LRs) with large language models (LLMs) and evaluate agreement with literature‑reported LRs using multiplicative Bland–Altman analysis and ordinal agreement metrics.

**Notebooks**
- `lr_scraper_estimator.ipynb` — builds prompts and calls OpenAI models to estimate LRs, writing a filled spreadsheet.
- `data_analysis.ipynb` — computes bias/LoA, coverage limits (50–99%), subgroup tests, ordinal agreement (Cohen’s κ), and generates publication‑ready figures/tables.

Preprint link: coming soon
Publication link: coming less soon

---

## Quick start (UV: reproducible Python env)

1. **Install uv; create and activate a virtual env**
```bash
pip install uv
uv venv --python 3.11
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell:
.venv\Scripts\Activate.ps1
```

2. **Install dependencies (creates `uv.lock`)**
```bash
uv sync
```

3. **Set secrets**
Create a file named `.env` at the repo root:
```ini
OPENAI_API_KEY=sk-...
```
(see .env.example)

4. **Launch Jupyter**
```bash
uv run jupyter lab
```

The notebooks will run with the exact, pinned versions in `uv.lock`.

---

## Repository layout

```
.
├── lr_scraper_estimator.ipynb
├── data_analysis.ipynb
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
├── results/                 # outputs; dated subfolders are created automatically
└── README.md
```

---

## What you should customize

### In `lr_scraper_estimator.ipynb`
- **I/O paths**: `INPUT_FILE`, `OUTPUT_FILE` (Excel paths).
- **Models**: `MODELS` (e.g., `"gpt-5"`, `"gpt-5-mini"`, `"gpt-4o-2024-11-20"`, `"o3-2025-04-16"`).
- **Model flags**: `MODEL_CAPABILITIES` (reasoning vs non‑reasoning; verbosity support).
- **Prompt scaffolding**: `SYSTEM_CORE`, `DEFINITION`, `BANDS`; few‑shot exemplars `FEW_SHOT_RICH` / `FEW_SHOT_MIN`.
- **API behavior**: set reasoning effort for reasoning models (e.g., `"medium"`).

### In `data_analysis.ipynb`
- **Output dirs**: `WORKING_DIR`; auto‑dated `OUTPUT_DIR = results/YYYY-MM-DD` is created if missing.
- **Model columns**: choose which LR columns to analyze and plot.
- **Ordinal bands**: `CATS` and `LR_BANDS` used for κ and plots.
- **Plot style**: the notebook sets Matplotlib to **DejaVu Sans** to avoid Unicode glyph warnings (≤, ≥, –).

---

## Reproduce a run non‑interactively (optional)

```bash
uv run papermill lr_scraper_estimator.ipynb out/scraper_run.ipynb
uv run papermill data_analysis.ipynb      out/analysis_run.ipynb
```

---

## Troubleshooting

- **OpenAI error**: ensure `OPENAI_API_KEY` is set and you have access to the specified model IDs.
- **Glyph warnings (≤, ≥, –)**: keep the default DejaVu Sans settings in the analysis notebook or escape math as `$\leq$`/`$\geq$`.
- **Missing packages**: run `uv sync` to install exact dependencies from `pyproject.toml`/`uv.lock`.

---

## License & citation

- License: MIT (see `LICENSE`).
- Please cite the repository and accompanying manuscript when using these materials.
