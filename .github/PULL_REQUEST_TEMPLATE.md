## Summary

Describe the release, reproducibility, data, or documentation change.

## Plan and contract effects

- [ ] The [repository instructions](../AGENTS.md) were reviewed.
- [ ] A plan using the [execution-plan template](../PLANS.md) is linked, or the
      change is small enough that no long-form plan is needed.
- [ ] Affected project metadata, schemas, release contracts, command
      interfaces, and frozen contracts are identified.
- [ ] Any unresolved scientific or release decision remains explicitly pending.
- [ ] `ANALYSIS_SPEC.md`, stable registers, and metadata registries agree with
      executable behavior, or are explicitly unaffected.

## Scientific-output impact

- [ ] No frozen input, model output, prompt, statistical method, figure data, or accepted result changed.
- [ ] Any intentional new replication is isolated under a new run ID.
- [ ] The historical v1 manifest and schema remain byte-identical.

## Validation

- [ ] `uv lock --check`
- [ ] `make setup`
- [ ] `make smoke`
- [ ] `make validate-metadata`
- [ ] `make audit`
- [ ] `git diff --check`
- [ ] `git diff --cached --check`
- [ ] If this is a release candidate, `make release-check` passed with the
      explicit reviewed contract and candidate ref.

## Public-release hygiene

- [ ] No credentials, private submission materials, proofs, local paths, or unreviewed generated artifacts are included.
- [ ] Citation, article status, version, and release metadata remain consistent.
- [ ] No live request was made by a reproduction, validation, test, smoke, or
      audit command.

## Handoff evidence

List files changed, contracts affected, exact commands and outcomes,
protected-artifact parity, output differences, optional checks not run,
approvals still pending, and residual risks.
