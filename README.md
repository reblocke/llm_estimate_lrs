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

See [`CLAUDE.md`](CLAUDE.md) for repository layout, customization points, troubleshooting, and developer/agent instructions.

---

## License & citation

- License: MIT (see `LICENSE`).
- Please cite the repository and accompanying manuscript when using these materials.
