# Known issues

## KI-001 — Evidence-direction wording order

**Affected artifacts:** accepted manuscript wording and executable
`results/reference/evidence_direction_tests.csv`
**Status:** disclosed; frozen artifacts preserved
**Scientific effect:** the rounded pair and inference are unchanged, but the o3
negative/positive stratum labels are reversed in one manuscript sentence
relative to executable assignment
**Resolution:** do not silently edit or relabel v1 artifacts; retain this
disclosure and evaluate any published correction separately

The author-manuscript sentence reports o3 as 0.95x for negative evidence and
1.03x for positive evidence. The executable analysis assigns
1.0326838754 to negative evidence and 0.9504718609 to positive evidence
(Welch `P = 0.1454697`).

## KI-002 — Incomplete historical provenance

**Affected artifacts:** row-level source fields, model-query audit, and curation
records
**Status:** not recovered; non-blocking for numerical reproduction
**Scientific effect:** limits source-level and process-level auditability but
does not alter frozen inputs or recalculated outputs
**Resolution:** preserve blanks and
`data/provenance/provenance_gaps_v1.csv`; add evidence only if an authoritative
historical record is recovered

## KI-003 — GPT-5 alias drift

**Affected artifacts:** accepted GPT-5 configuration and any future live
replication
**Status:** historical limitation
**Scientific effect:** a future provider request using the same alias may not
behave like the accepted run
**Resolution:** use frozen outputs for reproduction; treat every live rerun as
a separately versioned replication

## KI-004 — Independent reviews remain pending

**Affected artifacts:** `ANALYSIS_SPEC.md`, rights registry, and project
verification metadata
**Status:** `PENDING_HUMAN_REVIEW`
**Scientific effect:** automated checks establish internal consistency, not
independent scientific, statistical, legal, or reproducibility certification
**Resolution:** retain pending status until named human reviewers complete and
record their reviews
