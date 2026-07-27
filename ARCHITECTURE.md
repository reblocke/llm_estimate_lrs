# Architecture

## Purpose and current status

This repository is a maintenance-only reproducibility package for an accepted
paper. Its current architecture separates the immutable accepted-paper record,
offline numerical reproduction, guarded live replication, and
release-integrity tooling. Automated checks establish engineering integrity;
they do not constitute human scientific certification or publication.

## Immutable accepted-paper record

The accepted record consists of the source workbooks; curated, model-output,
provenance, and threshold data; accepted configuration and prompts; frozen
reference results; four historical notebooks; the manuscript text
representation; and the v1 manuscript manifest and schema.

These artifacts are inputs to maintenance checks, never generated targets.
They remain anchored to the `v1.0.0` Git objects. Adding maintenance
infrastructure changes the current-tree checksum inventory but must not change
an accepted artifact or its historical blob.

## Offline numerical reproduction

`make reproduce` invokes `scripts/reproduce_paper.py` in explicit offline mode.
The entry point reads the canonical local dataset, calls the existing
calculation implementation in `scripts/compute_reference_results.py`, writes
only to the ignored reproduction-run directory, and compares the generated
machine-readable outputs with `results/reference/`. Socket construction is
blocked during the calculation.

`make smoke` is the fast integrity path. It checks the lock, current-tree
checksums, project and release contracts, scientific/data/rights/output
metadata, and semantic data invariants.
`make audit` extends that path with repository hygiene, citation validation,
lint, tests, offline reproduction, and Git diff checks. Neither target invokes
the live replication runner, a hosted API, or another network-dependent
command. Dependency provisioning is isolated in `make setup`; validation uses
the existing root and CFF environments with offline, no-sync execution and
fails rather than creating a missing environment.

Routine numerical reproduction does not execute the historical notebooks.
Release-asset tooling may execute copies of the two offline analysis notebooks
in a temporary workspace; it does not overwrite the accepted notebooks.

## Guarded live replication

`make replicate` invokes `scripts/run_replication.py`. This path is outside
reproduction and audit. It requires an explicit experiment, exact model list,
call ceiling, confirmation, and unique run identifier before any live request.
Outputs belong to a new run directory and cannot replace accepted workbooks,
model outputs, or reference results. A missing or changed model must not cause
automatic substitution.

## Integrity and release contracts

The integrity layer has complementary records:

- `checksums/SHA256SUMS` inventories the reviewed current tree and therefore
  changes when tracked maintenance files change.
- `release/contracts/v1.0.0.json` is a post-release governance record. It
  validates immutable facts and protected blobs at the historical tag even
  after the default branch advances.
- `manifests/manuscript_run_v1.json` is part of the accepted tag-scoped
  scientific record. It is validated against the historical snapshot and is
  never regenerated for current tooling.

Historical contract validation and release-candidate validation are separate.
The former checks fixed tag, tree, annotation, and artifact facts. The latter
uses a clean governance checkout containing the current validator and reviewed
contract. It resolves the candidate ref once, reads that exact tree and its
blobs directly from the local Git object database, and writes their exact bytes
and executable modes into a temporary non-Git directory. This filter-free
materialization does not run Git checkout, repository or configured hooks, or
smudge/process filters. Every candidate filesystem and checksum check uses that
directory. The supplied ref is resolved again before cleanup so a ref that
moves during validation fails closed. Git subprocesses disable lazy fetching
and replacement objects, reject partial/promisor clones, and require the
candidate object closure to be available locally before materialization. The
complete history policy is evaluated again after candidate filesystem
validation so late changes to contracted branch, tag, or namespace refs fail
the run.

Prepare and final validation use the same contract but have different namespace
requirements. Prepare requires the contracted candidate commit and tree,
requires the intended tag to be absent, and applies default-branch and history
policy without tag parity. Final repeats those checks and additionally requires
the approved annotated tag, tag message, and candidate/default-branch/tag
identity. The governance contract is merged only after final validation, so it
is a post-release record rather than a self-referential member of the candidate
commit. The exceptional parentless single-root history belongs to v1 and is not
a default requirement for future contracts.

Release-asset construction reads archive and notebook inputs from the pinned
candidate Git objects, but its validation report is produced by the governance
checkout's current validator with the full candidate commit. Candidate-local
legacy validation tooling is never executed. Full contract validation and an
immediate candidate-ref recheck complete before either accepted notebook is
executed. Contract validation is repeated after notebook execution and before
attestation so namespace changes during asset construction also fail closed.

Historical manifest tests require a complete local v1 object closure and
disable Git lazy fetching for every historical blob or archive read.

## Scientific, data, rights, and output contracts

`ANALYSIS_SPEC.md` is a documentary rendering of the analysis that already
exists. It records the population, transformations, comparison directions,
formula families, random-number consumption order, tolerances, limitations,
and known deviations. It remains draft pending independent statistical review
and does not override the frozen executable artifacts.

The registries under `metadata/` provide stable IDs for source artifacts,
exact column-level semantics for every tracked public CSV, class-level rights
status, and accepted-output traceability. `scripts/validate_metadata.py`
enforces strict schemas, safe regular paths, artifact hashes, exact
column/output/crosswalk coverage, categorical-value compatibility, rights
classes, and resolvable input IDs. Pending rights and review states are valid
only when they remain explicit.

These are advancing-tree governance records. The v1 manifest, schema, release
contract, and tag are not retroactively rewritten to include them. Every
successor release contract must declare the complete current metadata and
schema set and validate it inside the materialized candidate tree.

## Trust boundaries

Frozen local artifacts become trusted inputs only after checksum, contract, and
semantic validation. Generated reproduction output is untrusted until it
matches the reference contract. Paths and archives cross a public-release
boundary and are screened for traversal, links, credentials, private material,
and process residue.

Network access and service credentials are outside the reproduction trust
boundary. They are permitted only in an explicitly approved live replication
and must not enter tracked files or logs. Missing provenance remains missing;
neither offline nor live tooling may infer it.

## Historical notebooks and manifest semantics

The four accepted notebooks are historical scientific artifacts. They preserve
the submitted workflows and are not successor interfaces for ongoing
development. Their duplicated analytical logic has not yet been replaced by a
shared importable core.

The v1 manuscript manifest describes the tree that was accepted and released,
including the tooling that existed in that tree. Current maintenance code
materializes or reads the v1 snapshot when validating that record; it does not
reinterpret the manifest as an inventory of the advancing default branch.

## Deliberately absent components

There is not yet a shared analytical package, a set of successor notebooks, or
an independent statistical oracle suite. The analysis specification and
registries exist, but their independent statistical, rights, reproducibility,
and high-risk reviews remain pending. There is no completed human
certification. Those later-stage outcomes must not be inferred from automated
contract validation.
