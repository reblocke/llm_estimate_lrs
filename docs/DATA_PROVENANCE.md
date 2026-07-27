# Data provenance and reuse boundaries

## Study data flow

The accepted analysis compares literature-reported diagnostic likelihood ratios with model-generated values.

1. On 1 April 2025, literature-reported LRs were collected from TheNNT diagnostic LR pages.
2. Automated extraction was followed by duplicate independent manual validation and reconciliation.
3. When a source provided both a point estimate and a range, the point estimate was retained.
4. When only a range was available, its geometric mean was used, consistent with the accepted methods.
5. On 25 August 2025, the three manuscript model configurations generated comparator LRs.
6. The accepted analysis workbook was assembled and manually validated.
7. For the `v1.0.0` paper snapshot, deterministic scripts export the frozen
   values into tidy CSV files and verify a one-to-one crosswalk without
   changing row order or accepted values.

Release `v1.1.0` retains these data and outputs unchanged while improving their
documentation, metadata, and offline validation.

## Source workbooks

`NNT_LRs_08-26-2025.xlsx`, sheet `Master`, is the numerical source for the accepted analysis. `nnt_lrs_with_estimated.xlsx` retains the per-condition worksheets, source-sheet context, and full condition labels where the corresponding worksheet cell is recoverable.

The workbooks are immutable. The canonical file `data/curated/diagnostic_lrs_manuscript_v1.csv` is an additive representation with stable IDs `lr_0001` through `lr_0700`. Its crosswalk key combines finding, reported LR, the three manuscript model outputs, and occurrence index within repeated values. A release is invalid unless all 700 rows match one-to-one.

## Raw and curated fields

Raw source strings are retained in `*_raw` fields. Curated display or analysis values occupy separate fields. A curated difference is valid only when it has a recoverable record in `data/provenance/curation_log_v1.csv`; otherwise the field remains unchanged and the missing rationale is recorded in `provenance_gaps_v1.csv`.

Blank provenance fields mean unavailable. They do not mean that a source, event, or review did not occur.

## Repeated rows and source context

Some condition–finding combinations occur more than once because the source presented them in different tables or contexts. The release preserves every accepted row in workbook order. It does not silently deduplicate apparently repeated records or infer a source-table identifier that was not historically recorded.

Excel worksheet names are limited to 31 characters. The canonical export stores the worksheet label separately from a full condition label recovered from the validated worksheet content. The exporter must fail rather than use a fuzzy match when a unique mapping cannot be established.

## Feature labels and LR categories

The five feature memberships are signs/symptoms, history, test result, imaging, and diagnostic adjudication. Memberships overlap by design: the expected counts sum to 725 across 700 rows. The original feature label is retained with the derived Boolean memberships.

Qualitative LR categories are defined in `config/analysis_categories_v1.json`. That versioned file, not prose documentation, is the executable boundary definition.

## Model outputs and query provenance

The manuscript model set contains exactly GPT-4o (`gpt-4o-2024-11-20`), o3 (`o3-2025-04-16`), and GPT-5 (`gpt-5`). GPT-4.1 values retained in a historical workbook are auxiliary and were not analyzed in the accepted manuscript.

Accepted outputs are immutable observations. Versioned prompt files preserve the historical text and model-specific example selection exactly, including historical wording. A future corrected prompt is a new research artifact and cannot replace the v1 prompt.

## Known provenance gaps

The following row-level information was not recoverable for every historical record:

- exact TheNNT page URL, table identifier, and retrieval timestamp;
- original model response ID and raw provider response JSON;
- exact request timestamp, retry count, and retry reason;
- exact SDK patch version used for every request;
- detailed rationale and reviewer identity for every historical manual correction.

The release records these limitations in `data/provenance/provenance_gaps_v1.csv` and the manuscript manifest. No missing URL, timestamp, response identifier, retry record, or curation explanation is reconstructed from inference.

## Reuse boundaries

The repository’s MIT License applies only to original software. It does not grant rights in third-party or literature-derived content.

- **Original repository code:** covered by the repository MIT License.
- **Author-generated model-output tables and curation/feature labels:** distributed for research transparency with their recorded provenance; the repository does not assert that the MIT software license governs every data field.
- **Literature-reported and TheNNT-derived values:** remain attributable to their original sources and may be subject to source terms; they are not relicensed as MIT data.
- **Provider outputs:** remain subject to applicable provider terms in addition to any rights held by the authors.
- **Article text:** `llms-full.txt` is a format-only pre-production author-manuscript representation shared under [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/) ([legal code](https://creativecommons.org/licenses/by-nc-nd/4.0/legalcode.en)). The representation changes format only; redistribution must be attributed and noncommercial, and adapted material may not be distributed. It is not the publisher Version of Record and does not include embedded figures.
- **Publisher-formatted material:** publisher proofs, layout files, and the Version of Record are not included in the repository.

Users are responsible for evaluating the source terms that apply to their intended reuse.
The machine-readable [data-source registry](../metadata/data_sources.csv)
records artifact paths and hashes, while the
[rights registry](../metadata/rights_and_licenses.yml) records these
class-level boundaries. An unresolved or unreviewed registry entry is not
permission to reuse the associated material.
