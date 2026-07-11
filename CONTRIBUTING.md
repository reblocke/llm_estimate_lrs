# Contributing

Contributions should preserve the frozen accepted-paper record while keeping reproduction auditable and offline.

## Environment

Use Python 3.11 and the locked environment:

```bash
pip install uv
uv sync --frozen
make kernel
```

Do not replace the lockfile with an unconstrained environment or add a parallel requirements file.

## Branches and pull requests

- Create a focused branch from the current default branch.
- Keep scientific, tooling, and documentation changes separable when practical.
- Explain the intended behavior, affected frozen contracts, and verification performed.
- Avoid broad notebook reformatting, regenerated figures, or unrelated cleanup.
- Never include credentials, private correspondence, publisher proofs, restricted data, local paths, or unreviewed drafts.

## Frozen artifacts

Do not edit the two accepted workbooks, accepted model outputs, v1 prompts, v1 model configuration, threshold outputs, reference results, or accepted analysis formulas. Raw values and curated values must remain separate. Missing provenance must be recorded as unavailable, never inferred.

A change to the principal dataset, manuscript model set, prompt, inference settings, or accepted analysis contract requires a new major version. Documentation and packaging fixes may use a patch version when all frozen hashes and results remain unchanged.

## Reproduction

The reproduction path must not require credentials or network access. Run:

```bash
make reproduce
make test
make release-check
git diff --check
```

`make reproduce` must make no OpenAI API calls and no live TheNNT requests. It must not overwrite tracked artifacts.

## New replications

A new live run is a replication. Use a run ID matching `YYYY-MM-DD_<short-description>_<git-short-sha>` and the guarded `make replicate` target. Every replication must use a new output directory and include its run manifest, prompt snapshot, query audit, raw outputs, analysis outputs, and checksums.

Never write replication outputs over the accepted workbooks, `data/model_outputs/manuscript_*`, or `results/reference/`. Do not commit credentials or unrestricted provider response payloads.

## Tests and documentation

- Add or update a focused test for changed behavior.
- Keep the article title, DOI, version, model identifiers, repository URL, and reproduction command consistent across public documentation.
- Record user-visible changes in `CHANGELOG.md` and release-facing changes in `RELEASE_NOTES_v1.0.0.md`.
- Run `make release-check` before requesting review.

Publishing a tag or GitHub release, replacing default-branch history, changing repository visibility, or deleting an existing release requires explicit maintainer approval.
