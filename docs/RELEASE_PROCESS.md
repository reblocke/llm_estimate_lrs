# Release process

This runbook covers maintenance releases that preserve the accepted-paper
record. The immutable `v1.0.0` tag remains the exact paper snapshot. A later
maintenance release may improve documentation, metadata, validation, or
packaging only when every protected artifact and accepted result remains
unchanged.

Read [PROJECT.yml](../PROJECT.yml), [AGENTS.md](../AGENTS.md), and the selected
versioned release contract before beginning. Automated validation does not
constitute independent scientific, statistical, reproducibility, rights, or
high-risk review.

## Release boundaries

- Reproduction is offline and recalculates accepted results from frozen local
  inputs. It never calls a model service or reconstructs a missing artifact.
- Replication is a new experiment and is outside the release gates.
- The v1 manuscript manifest and all protected artifact hashes remain anchored
  to `v1.0.0`.
- Redistribution authority for every release asset must be recorded before a
  public tag or release is created. If authority is incomplete, stop before
  tagging or publish an explicitly approved narrower asset set.
- Release-specific Make targets have no implicit contract or candidate ref.
  Supply both `RELEASE_CONTRACT` and `RELEASE_REF` on every invocation.

## Candidate and governance commits

A maintenance release uses two commits:

- Candidate commit `C` is the exact tree tagged and distributed.
- Governance commit `G` is created after `C`. It adds the release contract and
  updated current-tree checksum record that bind `C` without a self-reference.

The contract lives in a clean governance checkout at `G`, while validation and
asset construction read the candidate tree directly from Git objects at `C`.
The contract must record the full commit and tree IDs, the release publication
date, the exact annotated-tag message, the immutable prior-tag binding, the
protected hashes, and the allowed branch and tag namespace.

For `v1.1.0`, use:

- contract: `release/contracts/v1.1.0.json`
- release ref: `v1.1.0`
- release date: `2026-07-27`
- tag message: `Reproducibility and metadata maintenance release`
- release title: `v1.1.0 — Reproducibility and metadata maintenance release`
- release body: the exact contents of `RELEASE_NOTES_v1.1.0.md`

## 1. Candidate preflight

From the candidate checkout, provision the locked environments once and run
the complete offline gates:

```bash
uv lock --check
make setup
make smoke
OPENAI_API_KEY="" make audit
git diff --check
git diff --cached --check
git status --short
```

The candidate must be clean. Confirm that all protected hashes and accepted
reference results are unchanged, and report an unavailable optional private
author-DOCX comparison separately rather than treating it as passed.

Record `C` and its tree from the final reviewed candidate. Ensure the canonical
default-branch ref resolves to `C`, only the allowed branch remains, and
`v1.0.0` still resolves to its original commit and tree.

## 2. Contracted prepare validation

In the clean governance checkout containing the reviewed contract, run:

```bash
make release-check \
  RELEASE_CONTRACT=release/contracts/v1.1.0.json \
  RELEASE_REF=CANDIDATE_COMMIT
```

Prepare validation requires the intended tag to be absent. It validates all
historical contracts, materializes `C` without checkout hooks or filters,
checks candidate metadata and checksums, verifies the allowed refs and prior
tag, runs the offline reproduction and tests, builds the versioned assets, and
scans the resulting archive set.

Do not proceed if the candidate ref, default branch, contract, protected
inventory, checksum inventory, or namespace changes during validation.

## 3. Tag and final validation

After the rights and maintainer approvals are recorded, create the annotated
tag at exactly `C`:

```bash
git tag -a v1.1.0 CANDIDATE_COMMIT \
  -m "Reproducibility and metadata maintenance release"
```

Then run final validation and the two-build determinism check from the same
clean governance checkout:

```bash
make release-check-final \
  RELEASE_CONTRACT=release/contracts/v1.1.0.json \
  RELEASE_REF=CANDIDATE_COMMIT
make release-assets-determinism \
  RELEASE_CONTRACT=release/contracts/v1.1.0.json \
  RELEASE_REF=CANDIDATE_COMMIT \
  RELEASE_MODE=final
make archive-hygiene \
  RELEASE_CONTRACT=release/contracts/v1.1.0.json \
  RELEASE_REF=CANDIDATE_COMMIT
```

Final validation requires the candidate, default branch, audited commit, and
annotated tag to agree exactly. Asset construction pins `C`, reads all source
bytes from its tree, repeats contract validation after notebook execution, and
fails if the ref or working tree moves.

## 4. Release assets

The asset builder derives archive names and the required inventory from the
contract release version. The complete `v1.1.0` asset set is:

- `llm-estimate-lrs-v1.1.0.zip`
- `reference-tables-v1.1.0.zip`
- `notebooks/data_analysis.executed.ipynb`
- `notebooks/supplementary_analyses.executed.ipynb`
- `validation-report.json`
- `release-attestation.json`
- `SHA256SUMS`

The source and reference archives are deterministic. The executed notebooks
run from temporary copies with external network access blocked. The attestation
records the contracted version and tag, the requested candidate ref, the
resolved commit, the article DOI, and every pre-attestation asset hash.
`SHA256SUMS` then covers the attestation and every other asset without hashing
itself.

No regenerated figure, office export, provider response payload, private
correspondence, or publisher proof is an approved release asset.

## 5. Draft release verification

Push the tag only after final validation succeeds and require the tag workflow
to pass. Tag CI intentionally runs the tagged candidate's offline audit and
public-text hygiene without requiring the post-release contract, because that
contract is not part of `C`.

Create a draft release with the exact title and notes above, attach only the
seven approved files, and download the draft metadata and assets into a fresh
temporary directory. Verify asset checksums and run the contract-driven exact
title/body check:

```bash
uv run --offline --no-sync python scripts/check_release_hygiene.py \
  --repository . \
  --contract release/contracts/v1.1.0.json \
  --release-json DRAFT_RELEASE.json \
  --asset-dir DOWNLOADED_ASSETS
```

Publish only after the downloaded inventory, hashes, title, body, tag, and
commit all match the reviewed records. The release-event workflow provides an
additional generic scan of the public title/body and tagged tree; the
contract-driven draft check is the authoritative exact comparison.

## 6. Post-release governance and closure

After publication, fast-forward `main` to `G` and push the governance record.
Remove temporary release branches and worktrees only after exact containment
or tree-equivalence checks and preservation of any unique local changes.

The final report records:

- candidate and governance commit IDs and the v1.1 tag object;
- exact commands run and their results;
- protected-artifact, reference-result, and checksum comparisons;
- the deterministic asset inventory and hashes;
- GitHub release and tag-CI status;
- branch, worktree, stash, tag, and remote-ref inventory;
- rights approval and any unavailable optional private-source check; and
- all remaining human approvals or residual risks.

Completion requires one clean local `main` worktree, one local branch, one
remote branch, `origin/HEAD` pointing to `origin/main`, the unchanged
`v1.0.0` tag, the new `v1.1.0` tag and Latest release, and no live model call
from any validation or publication gate.
