# AGENTS

## Project Purpose
LLM-generated likelihood-ratio outputs for diagnostic evidence and agreement with literature-reported values

## Public and Data-Safety Rules
- Treat this repository as public. Do not add PHI, restricted datasets, credentials, private drafts, or publisher-formatted article text.
- Generated LLM outputs and literature-derived comparison data; avoid adding API keys or private prompts.
- Manuscript status: No publication DOI is assigned in this repository; use repository README and commit SHA for reuse.

## How to Orient Quickly
- Start with `README.md` for project scope, workflow, data notes, citation, and license information.
- Use `CITATION.cff` for structured citation metadata when present.
- Inspect scripts/notebooks before running them; do not assume generated outputs are current.

## Workflow
From the repository root, use this as the initial run guidance:

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt; then open the relevant notebook or run the README-defined command.
```

If the command is a placeholder, refine it after reading the local scripts and existing README.

## Verification Before Publishing Changes
- Run `git diff --check`.
- Validate `CITATION.cff` as YAML after citation edits.
- Do not commit generated outputs, logs, caches, virtual environments, `.DS_Store`, or checkpoint files unless intentionally released.
- For clinical or collaborator data, confirm that no row-level restricted data or identifiers are included.
