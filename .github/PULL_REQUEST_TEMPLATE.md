## Summary

Describe the release, reproducibility, data, or documentation change.

## Scientific-output impact

- [ ] No frozen input, model output, prompt, statistical method, figure data, or accepted result changed.
- [ ] Any intentional new replication is isolated under a new run ID.

## Validation

- [ ] `uv sync --frozen`
- [ ] `make release-check`
- [ ] `git diff --check`

## Public-release hygiene

- [ ] No credentials, private submission materials, proofs, local paths, or unreviewed generated artifacts are included.
- [ ] Citation, article status, version, and release metadata remain consistent.
