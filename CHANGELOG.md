# Changelog

All notable changes to this repository are documented here.

## [1.0.0] - Unreleased

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
