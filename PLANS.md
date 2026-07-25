# Execution-plan template

Use this template for work that spans multiple milestones or contracts, changes
release behavior, or carries scientific or public-release risk. Keep the plan
current as implementation proceeds.

## Objective

State the intended outcome and the user-visible problem it solves.

## Baseline and current behavior

Record the starting ref or commit, relevant existing behavior, and evidence from
checks run before editing.

## Invariants

List the scientific, data, security, history, and compatibility properties that
must remain unchanged.

## Scope

### In scope

List the files, interfaces, and behaviors the change is authorized to affect.

### Out of scope

List adjacent work that is deliberately deferred.

## Milestones

For each milestone, record:

- the changes and files involved;
- the affected contracts;
- the validation to run;
- the rollback approach; and
- decisions that require approval.

## Contract effects

Identify every schema, release contract, file-format contract, command
interface, frozen artifact, and expected-output contract touched. State
explicitly when there is no scientific-output effect.

## Validation

List exact commands, fixtures, expected results, offline requirements, and any
manual inspection. Distinguish required checks from optional checks that may be
unavailable.

## Approval decisions

Record decisions made, decision owners, unresolved choices, and actions that
need new authority before they can proceed.

## Risks and mitigations

Describe silent-failure modes, their likely impact, and the check or control
that addresses each one.

## Rollback

Explain how to reverse implementation changes without moving a published tag,
rewriting accepted history, or replacing a protected artifact.

## Completion evidence

Record the final ref, files changed, contracts affected, commands and outcomes,
protected-artifact parity, output differences, approvals still pending, and
residual risks.

## Deviations from the approved plan

Document any deviation and its approval. Write `None` when implementation
matches the approved plan.
