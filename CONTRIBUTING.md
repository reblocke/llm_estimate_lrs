# Contributing

Contributions should preserve the frozen accepted-paper record while keeping reproduction auditable and offline.

## Environment

Use Python 3.11 and the locked environment:

```bash
pip install uv
uv lock --check
make setup
make kernel
```

Do not replace the lockfile with an unconstrained environment or add a parallel requirements file.
`make setup` is the explicit provisioning step; `make smoke` and `make audit`
must use the provisioned environments without syncing or network access.

## Branches and pull requests

- Create a focused branch from the current default branch.
- Keep scientific, tooling, and documentation changes separable when practical.
- Explain the intended behavior, affected frozen contracts, and verification performed.
- Use [`PLANS.md`](PLANS.md) for work spanning multiple milestones or contracts
  and keep approval decisions visible.
- Avoid broad notebook reformatting, regenerated figures, or unrelated cleanup.
- Never include credentials, private correspondence, publisher proofs, restricted data, local paths, or unreviewed drafts.

## Frozen artifacts

Do not edit the two accepted workbooks, accepted model outputs, v1 prompts, v1
model configuration, threshold outputs, reference results, accepted notebooks,
manuscript text representation, or accepted analysis formulas. The v1
manuscript manifest and schema are historical tag-scoped records and must remain
byte-identical. Raw values and curated values must remain separate. Missing
provenance must be recorded as unavailable, never inferred.

A change to the principal dataset, manuscript model set, prompt, inference settings, or accepted analysis contract requires a new major version. Documentation and packaging fixes may use a patch version when all frozen hashes and results remain unchanged.

## Reproduction

The reproduction and maintenance gates must not require credentials or network
access. During development, run the fast gate; before requesting review, run
the complete gate:

```bash
make smoke
make audit
git diff --check
git diff --cached --check
```

`make audit` includes the offline reproduction and test suite. It must make no
live model or web requests and must not overwrite tracked artifacts.
`make release-check` is an additional release-candidate operation, not a
substitute for the routine audit.

## New replications

A new live run is a replication. Use a run ID matching `YYYY-MM-DD_<short-description>_<git-short-sha>` and the guarded `make replicate` target. Every replication must use a new output directory and include its run manifest, prompt snapshot, query audit, raw outputs, analysis outputs, and checksums.

Never write replication outputs over the accepted workbooks, `data/model_outputs/manuscript_*`, or `results/reference/`. Do not commit credentials or unrestricted provider response payloads.

## Tests and documentation

- Add or update a focused test for changed behavior.
- Keep the article title, DOI, version, model identifiers, repository URL, and reproduction command consistent across public documentation.
- Keep [`PROJECT.yml`](PROJECT.yml), [`ARCHITECTURE.md`](ARCHITECTURE.md), and
  the affected versioned release contract consistent with implemented
  behavior.
- Keep [`ANALYSIS_SPEC.md`](ANALYSIS_SPEC.md), the stable registers, and
  [`metadata/`](metadata/) consistent with frozen executable behavior. Never
  turn a pending scientific or rights field into an approval without the named
  human authority.
- Record user-visible changes in `CHANGELOG.md`. Do not revise the historical
  `v1.0.0` release notes to imply a new release.
- Run `make audit` before requesting review. Run `make release-check` with an
  explicit contract and candidate ref only when preparing a release candidate.

Publishing a tag or GitHub release, replacing default-branch history, changing repository visibility, or deleting an existing release requires explicit maintainer approval.
