# Repository instructions

## Purpose

This repository preserves the accepted-paper record for diagnostic
likelihood-ratio analyses. It supports deterministic offline reproduction,
guarded live replication, and maintenance of the public reproducibility
package.

## Setup and checks

Run commands from the repository root. Set up the locked environment with:

```bash
uv lock --check
make setup
```

`make setup` is the only routine setup command allowed to provision or
download dependencies. The validation targets below use the already
provisioned environments without syncing.

Use the fast offline gate during development:

```bash
make smoke
```

Use the complete offline engineering-integrity gate before handoff:

```bash
make audit
```

Focused checks are available when diagnosing a failure:

```bash
make validate-contracts
make validate-metadata
make test
make reproduce
```

## Protected artifacts

Treat the following accepted-paper artifact classes as immutable:

- the two source workbooks;
- curated, model-output, provenance, and threshold data;
- accepted prompts and model and analysis configuration;
- frozen reference results;
- the four accepted notebooks;
- the manuscript text representation; and
- the v1 manuscript manifest and its schema.

Do not modify, regenerate, reformat, or replace a protected artifact. The
current-tree checksum inventory is maintenance infrastructure and may be
regenerated only after the complete reviewed file set is present. A checksum
inventory update does not authorize any protected-artifact change.

## Reproduction and replication boundaries

Reproduction recalculates accepted numerical results from frozen local inputs.
It is offline, requires no credential, and must fail rather than access a
network or reconstruct a missing artifact.

Replication sends new requests to an external model service. It is a new
experiment, not reproduction. A replication requires an explicit request,
review of the exact model list and call ceiling, and a new output directory.
It is never part of `make smoke` or `make audit`.

## Non-negotiable rules

- Never make a live model, web, or other network call from a reproduction,
  validation, test, smoke, or audit path.
- Never substitute a model, model version, prompt, or inference setting
  automatically.
- Never infer unavailable provenance, curation rationale, or request metadata.
- Never update an expected result merely to make a failing check pass.
- Do not change the analysis population, formulas, categories, tolerances,
  interpretation, or accepted outputs without explicit scientific approval and
  version reclassification.
- Do not expose credentials, private correspondence, restricted material,
  publisher proofs, or unrestricted provider response payloads.
- Permit repository instructions only in this root file; do not add nested
  instruction files.

## Version classification

The v1 record is maintenance-only. Documentation, tooling, packaging, and
schema changes that preserve every protected artifact and accepted result are
patch or minor candidates, subject to maintainer review. A scientific-contract
or accepted-output change is outside routine maintenance and requires a
major-version decision and independent review. Do not claim a release or
certification solely because automated checks pass.

## Handoff evidence

Report the files changed, contracts affected, exact commands run, checksum and
protected-artifact results, output differences, unresolved human approvals,
and residual risks. Distinguish an unavailable optional private-source check
from a passed check.

## Definition of done

Work is complete only when the requested scope is implemented, `make smoke`
and `make audit` pass offline, diff checks are clean, protected artifacts and
accepted results are unchanged, no live request was made, documentation agrees
with behavior, and all unresolved approvals remain explicit.
