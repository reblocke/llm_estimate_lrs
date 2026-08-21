# Changelog

All notable changes to this repository are documented here.

## [Unreleased]

### Security

- Raised the locked jiter security floor to 0.16.0 while retaining OpenAI
  1.102.0 and Pydantic 2.11.7.

### Scientific results

- No accepted-paper input, prompt, model output, analysis, statistic, figure,
  or conclusion changed.

## [1.1.0] - 2026-07-27

### Added

- Public-safe repository instructions, machine-readable project metadata, and
  an initial architecture and execution-plan contract.
- A schema-validated, Git-object-anchored `v1.0.0` release contract with
  protected-artifact parity checks.
- Truthful offline `smoke` and `audit` entry points and contract validation in
  continuous integration.
- A draft scientific analysis specification, stable decision/exception/issue
  registers, and strict source, variable, rights, and accepted-output
  registries.
- Offline metadata validation with exact artifact, column, rights-class,
  crosswalk, and output coverage.
- A reader-first repository guide aligned with the published article and a
  separate current-release identifier that preserves `v1.0.0` as the
  accepted-paper snapshot.

### Changed

- Release validation now accepts an explicit versioned contract and candidate
  ref while retaining the exceptional `v1.0.0` history policy.
- The accepted v1 manuscript manifest is validated against its historical tag
  snapshot rather than advancing maintenance code.
- Release assets validate the contracted candidate before executing notebooks,
  materialize candidate blobs without checkout hooks or filters, and recheck
  contracted refs before success.
- Historical Git reads reject partial/promisor clones and disable lazy
  fetching and replacement objects.
- Every successor release contract must declare and validate the complete
  metadata and reproducibility contract set; historical v1 remains tag-scoped.

### Scientific results

- No accepted-paper input, prompt, model output, analysis, statistic, figure,
  or conclusion changed.

## [1.0.0] - 2026-07-11

### Added

- Accepted-paper reproducibility manifest and checksum inventory.
- Canonical machine-readable dataset with stable row identifiers.
- Versioned prompt and model-configuration artifacts.
- Frozen threshold outputs, reference results, and automated validation.
- Separate reproduction, replication, provenance, crosswalk, and release documentation.
- Continuous-integration checks for data integrity, offline execution, and release hygiene.
- Licensed, format-only pre-production author-manuscript text representation.

### Changed

- Updated article, citation, and repository status metadata.
- Distinguished frozen offline reproduction from live replication.
- Restricted the manuscript model configuration to the three accepted-paper models.
- Renamed the supplementary analysis notebook for a stable public-facing purpose.
- Replaced ad hoc environment guidance with the locked `uv` workflow.

### Fixed

- Added deterministic creation of reproduction output directories.
- Added a dedicated project kernel to prevent execution under an unrelated Python environment.
- Documented source, model-output, article-text, and software reuse boundaries separately.

### Scientific results

- No accepted-paper analysis, model output, statistic, figure, or conclusion was changed.

## Earlier history

Earlier development snapshots are superseded by the sanitized accepted-paper release.
