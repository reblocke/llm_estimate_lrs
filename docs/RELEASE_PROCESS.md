# Release process

This process prepares the GitHub-only `v1.0.0` accepted-paper reproducibility release. Merging, replacing default-branch history, changing repository visibility, deleting an earlier release, tagging, and publishing each require explicit maintainer approval.

## 1. Security and repository preflight

- Confirm any historically exposed credential has been revoked and its account activity reviewed.
- Verify the working branch is `release/accepted-paper-reproducibility-v1`.
- Confirm the default branch is frozen against collaborator writes during any approved history replacement.
- Verify ordinary remote branches, tags, release assets, and default-tree history contain only reviewed public material.
- Confirm collaborators understand that an approved history replacement requires a fresh clone.
- Do not claim that an ordinary force-push removes immutable hosting-provider references or every cached object.

## 2. Metadata and version

The release version, CFF version, release title, manifest release reference, archive name, and documentation must all use `1.0.0` / `v1.0.0`. Before the tag is created:

- change `CHANGELOG.md` from `Unreleased` to the approved release date;
- add the same `date-released` value to `CITATION.cff`;
- confirm that the article metadata still identifies the 11 July 2026 citable, unedited early-access publication and distinguishes it from the later production-edited Version of Record;
- verify the article title, DOI, eight-author order, and repository URL.

Do not add the software release date before the GitHub release is scheduled. The article publication date remains
`2026-07-11` and is independent of the later software release date.

## 3. Frozen-artifact validation

From a fresh clone of the reviewed branch:

```bash
pip install uv
uv lock --check
uv sync --frozen
make verify-checksums
make validate-data
make reproduce
make test
make release-check
git diff --check
git status --short
```

The final status must be clean. Reproduction must succeed without `OPENAI_API_KEY` and with network access blocked.

Release-blocking failures include changed workbook or prompt hashes, an incomplete 700-row crosswalk, missing/nonpositive/nonfinite manuscript outputs, changed expected metrics, absent frozen threshold evidence, invalid CFF/manifest data, network-dependent reproduction, or public inclusion of restricted/private files.

## 4. Checksums and archive

Regenerate checksums only through the deterministic checksum tool, then review the diff:

```bash
uv run python scripts/build_manifest.py
uv run python scripts/build_checksums.py --root . --output checksums/SHA256SUMS
uv run python scripts/verify_checksums.py checksums/SHA256SUMS
make release-archive
```

`make release-archive` builds the source archive, a deterministic reference-table archive, executed copies of the two offline analysis notebooks, a validation report, a release attestation, and an asset-level `dist/SHA256SUMS`. Notebook execution occurs from temporary workbook/notebook copies; generated figures and office files remain in the temporary workspace and are not release assets.

The source archive must exclude credentials, local environments, caches, generated reproduction runs, private correspondence, publisher proofs, stale office artifacts, and unreviewed drafts. Run the hygiene checker against both the repository and archive.

The tracked manifest records `release_ref: v1.0.0`. The generated release attestation records the actual tag commit and all pre-attestation asset hashes after tagging; the asset-level checksum file then covers the attestation as well. This avoids a self-referential commit hash inside the tagged tree.

## 5. CFF and documentation validation

```bash
make cff-validate
uv run pytest -q tests/test_documentation_consistency.py tests/test_manuscript_text.py
test -f "$AUTHOR_MANUSCRIPT_DOCX"
make manuscript-parity AUTHOR_MANUSCRIPT_DOCX="$AUTHOR_MANUSCRIPT_DOCX"
```

The maintainer-only `manuscript-parity` command is release-blocking. It requires the private author DOCX to exist and
runs the complete manuscript-text test module with the source round-trip active; no skipped source-parity test is
accepted. The DOCX remains outside the repository and release assets.

Confirm that README, CFF, release notes, machine index, manifest, and package metadata agree on version, title, DOI, repository URL, model identifiers, and reproduction command. Confirm `llms-full.txt` retains the source and visible-text hashes and is clearly labeled as a pre-production author manuscript rather than the Version of Record.

## 6. Approved clean-root transition, tag, and GitHub release

The following is a maintainer runbook, not an automatic workflow. Credential review, visibility changes, merging,
release/tag deletion, force-updating `main`, branch deletion, tagging, reopening the repository, and publishing the
release each require their own explicit approval. Stop at any failed check.

### 6.1 Final metadata and legacy-main merge

1. Confirm the historically exposed credential is revoked and review its usage and billing.
2. Choose the actual GitHub release date. Add it as top-level `date-released` in `CITATION.cff`, replace
   `Unreleased` in `CHANGELOG.md` with the same date, and replace prepare-state citation/status wording in
   `README.md`, `llms.txt`, and `RELEASE_NOTES_v1.0.0.md` with final language that identifies the published
   `v1.0.0` tag and release. Regenerate `checksums/SHA256SUMS`, run `make verify-checksums`, and include the checksum
   changes in review of that metadata-only commit before recording the reviewed tree. Do not change scientific wording
   or values in this transition.
3. Before merging, fetch the reviewed release branch and record its tree independently outside the repository:

```bash
git fetch origin --prune --tags
reviewed_tree=$(git rev-parse origin/release/accepted-paper-reproducibility-v1^{tree})
printf '%s\n' "$reviewed_tree" > "$HOME/llm_estimate_lrs-v1-reviewed-tree.txt"
```

4. After separate approval, temporarily make the repository private, freeze collaborator pushes, and merge the
   reviewed pull request into the legacy `main` branch.
5. Fetch the merged branch and verify its tree against that independently recorded value before any remote mutation:

```bash
git fetch origin --prune --tags
git switch main
git pull --ff-only origin main
old_main=$(git rev-parse origin/main)
reviewed_tree=$(cat "$HOME/llm_estimate_lrs-v1-reviewed-tree.txt")
merged_tree=$(git rev-parse HEAD^{tree})
test "$merged_tree" = "$reviewed_tree"
approved_tree=$reviewed_tree
clean_root=$(printf '%s\n' "Accepted-paper reproducibility release" | git commit-tree "$approved_tree")
test "$(git rev-parse "$clean_root^{tree}")" = "$approved_tree"
test "$(git rev-list --count "$clean_root")" -eq 1
```

The `git commit-tree` command creates a parentless local commit from the exact reviewed tree. It does not alter the
working tree or remote repository.

### 6.2 Approval-gated remote replacement

With separate approval for each externally visible operation:

```bash
gh release delete v0.1.0 --yes
git push origin :refs/tags/v0.1.0
git push --force-with-lease=refs/heads/main:"$old_main" origin "$clean_root":refs/heads/main
git push origin --delete release/accepted-paper-reproducibility-v1
```

Do not weaken or omit the explicit lease SHA. The immutable commits referenced by historical merged pull-request
refs remain a documented private risk exception; this process does not claim complete object or cache expungement.

### 6.3 Fresh-clone final gate and tag

Discard the transition clone. In a fresh full clone, verify the replacement before tagging:

```bash
set -euo pipefail
git clone https://github.com/reblocke/llm_estimate_lrs.git llm_estimate_lrs-v1
cd llm_estimate_lrs-v1
git fetch origin --prune --prune-tags
uv lock --check
make setup
reviewed_tree=$(cat "$HOME/llm_estimate_lrs-v1-reviewed-tree.txt")
test "$(git rev-list --count HEAD)" -eq 1
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"
test "$(git rev-parse HEAD^{tree})" = "$reviewed_tree"
! git merge-base --is-ancestor 9ab48f0244daff1b7c9ed58f2f4fca2572284f65 HEAD
! git show-ref --verify --quiet refs/tags/v0.1.0
! git ls-remote --exit-code --heads origin refs/heads/release/accepted-paper-reproducibility-v1
release_list=$(mktemp)
gh release list --repo reblocke/llm_estimate_lrs --limit 100 --json tagName > "$release_list"
jq -e 'all(.[]; .tagName != "v0.1.0")' "$release_list" > /dev/null
rm "$release_list"
git tag -a v1.0.0 -m "Accepted-paper reproducibility release"
make release-check-final
git push origin v1.0.0
remote_main=$(git ls-remote --heads origin refs/heads/main | cut -f1)
remote_tag=$(git ls-remote origin 'refs/tags/v1.0.0^{}' | cut -f1)
test "$remote_main" = "$remote_tag"
```

If the final-mode check fails, do not push. Delete only the unpublished local tag with `git tag -d v1.0.0`, correct
the reviewed tree through another approval cycle, and repeat the clean-root transition.

After the tag and `main` identities are verified, reopen the repository only with separate approval. Require every
collaborator to discard old clones and reclone before contributing. Reopening occurs before release assets or the
draft GitHub release are created.

### 6.4 Draft release verification and publication

After the repository is reopened, build assets only from the validated tag. Create a draft GitHub release titled
`v1.0.0 — Accepted-paper reproducibility release`, using `RELEASE_NOTES_v1.0.0.md` as the exact body. Attach only the
approved source archive, reference tables, executed verification notebooks, checksum file, validation report, and
release attestation. Do not attach regenerated figures unless they are byte-identical to approved submitted
artifacts.

```bash
make release-assets-determinism RELEASE_REF=v1.0.0 RELEASE_MODE=final
make archive-hygiene
```

The determinism target builds the complete asset set twice from the same reviewed commit and requires exact equality
of the relative-path/SHA-256 inventory, including both executed notebooks, the validation report, attestation, and
asset checksum file. The second verified build remains in `dist/` for draft upload.

Before publication, fetch and verify the actual draft title and body:

```bash
gh release create v1.0.0 --draft \
  --title "v1.0.0 — Accepted-paper reproducibility release" \
  --notes-file RELEASE_NOTES_v1.0.0.md
release_json=$(mktemp)
gh release view v1.0.0 --json name,body > "$release_json"
uv run python scripts/check_release_hygiene.py \
  --repository . --head-commit HEAD --release-json "$release_json"
rm "$release_json"
```

Upload and checksum-verify the reviewed assets while the release remains a draft. Publish the draft only after a
separate maintainer approval.

## 7. Post-release verification

- Resolve the tag and record its full commit SHA.
- Download every release asset into a clean temporary directory and verify the published checksums.
- Run the documented reproduction from the tagged source archive without credentials or network access.
- Confirm the GitHub release title, article DOI, repository topics, description, and citation prompt.
- Confirm the default branch and tag expose no private or temporary artifacts.

## 8. Rollback

If an asset or metadata-only document is wrong, remove the affected GitHub release asset or draft release, correct it on a reviewed branch, and prepare a patch release when the tag has already been published. Never move or silently replace a published tag.

If a frozen scientific artifact or accepted result differs, stop distribution of the release and investigate. Do not regenerate a historical model response or edit an accepted value to restore a check. A scientific-contract change requires explicit maintainer review and appropriate versioning.
