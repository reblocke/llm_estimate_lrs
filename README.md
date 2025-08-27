# llm_estimate_lrs

Estimate diagnostic likelihood ratios (LRs) with LLMs and evaluate agreement with literature‑reported LRs using multiplicative Bland–Altman analysis and ordinal agreement metrics. This repo contains two notebooks:

- `lr_scraper_estimator.ipynb` — builds prompts and calls OpenAI models to estimate LRs, writing a filled spreadsheet.
- `data_analysis.ipynb` — analyzes agreement (bias, LoA, coverage limits, subgroup tests) and ordinal agreement (Cohen’s κ), and generates publication‑ready figures/tables.


Preprint link: coming soon
Publication link: coming less soon

---

## Quick start (UV: reproducible Python without Conda)

1. **Install uv; create and activate a venv**
   ```bash
   pip install uv
   uv venv --python 3.11
   # macOS/Linux:
   source .venv/bin/activate
   # Windows PowerShell:
   .venv\Scripts\Activate.ps1
```

2. **Install dependencies (creates uv.lock)**
   ```bash
uv sync
```

3. **Set Secrets**

Create .env at repo root 

OPENAI_API_KEY=sk-...

(See .env.example)

4. **Launch Jupyuter**
   ```bash
uv run jupyter lab
```

## Repository layout

.
├── results/                   # outputs; dated subfolders are created automatically
├── lr_scraper_estimator.ipynb
├── data_analysis.ipynb
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
└── README.md

## What you will customize

In lr_scraper_estimator.ipynb
	•	File IO
	•	INPUT_FILE, OUTPUT_FILE (Excel paths for categories and filled outputs)
	•	Models
	•	MODELS (e.g., "gpt-5", "gpt-5-mini", "gpt-4o-2024-11-20", "o3-2025-04-16")
	•	MODEL_CAPABILITIES flags (reasoning vs non‑reasoning; verbosity support)
	•	Prompt scaffolding
	•	SYSTEM_CORE, DEFINITION, BANDS
	•	Few‑shot exemplars: FEW_SHOT_RICH, FEW_SHOT_MIN
	•	API behavior
	•	Reasoning effort (e.g., {"reasoning": {"effort": "medium"}})
	•	Any request throttling/backoff

In data_analysis.ipynb
	•	Output directories
	•	WORKING_DIR, and a dated OUTPUT_DIR = results/YYYY-MM-DD (auto‑created)
	•	Model columns / panels
	•	Which LR columns to analyze/plot (e.g., lr_gpt-5, lr_o3-2025-04-16, lr_gpt-4o-2024-11-20)
	•	Qualitative bands (ordered)
	•	CATS and LR_BANDS used in κ/plots
	•	Plot style
	•	Matplotlib font set to DejaVu Sans to avoid Unicode glyph warnings
	•	Export formats (PDF preferred; TIFF with LZW if required)


## Reproduce the paper’s outputs
	1.	Estimate LRs
Run all cells in lr_scraper_estimator.ipynb. Produces a filled workbook with model LR columns.
	2.	Analyze
Run data_analysis.ipynb to generate:
	•	Bland–Altman panels (log‑scale analysis; labels shown as LR fold)
	•	Coverage tables (50/75/90/95/99%) with 95% CIs in ×‑fold units
	•	Subgroup comparisons (Welch t; Levene (median))
	•	Ordinal agreement (percent agreement; Cohen’s κ unweighted/linear/quadratic; optional Fleiss κ across models)
	•	Publication‑ready figures and Word tables
	3.	Outputs
Saved under results/YYYY-MM-DD/.

## Troubleshooting
	•	OpenAI error: ensure OPENAI_API_KEY is set and the model IDs are available to your account.
	•	Glyph warnings (≤, ≥, –): the analysis notebook sets Matplotlib to DejaVu Sans; keep that or escape math as $\leq$.
	•	Missing packages: re‑run uv sync.


## License and citation
	•	License: see LICENSE.
	•	Please cite the repository and accompanying manuscript when using these materials.


tl;dr: What a new user can do exactly
	1.	git clone … && cd llm_estimate_lrs
	2.	pip install uv
	3.	uv venv --python 3.11 && source .venv/bin/activate  (Windows: .venv\Scripts\Activate.ps1)
	4.	uv sync  (creates uv.lock, installs pinned deps)
	5.	Copy .env.example → .env and paste your real OPENAI_API_KEY.
	6.	uv run jupyter lab and open the notebooks.
	7.	In lr_scraper_estimator.ipynb, set INPUT_FILE, OUTPUT_FILE, MODELS, etc. Run all.
	8.	In data_analysis.ipynb, set WORKING_DIR and confirm OUTPUT_DIR. Run all.
	9.	Outputs appear in results/YYYY-MM-DD
