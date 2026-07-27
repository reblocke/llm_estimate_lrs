# Metadata contracts

These registries describe the frozen accepted-paper artifacts without changing
them:

- `data_sources.csv` assigns stable IDs, paths, SHA-256 hashes, and an explicit
  `requires_live_service` classification to each governed input or data
  artifact. That classification is fixed by source ID rather than inferred
  from descriptive acquisition text.
- `variable_dictionary.csv` contains exactly one row for every column in each
  tracked CSV under `data/` and `results/reference/`. Registry CSVs and ignored
  generated runs are intentionally outside that recursive rule.
- `rights_and_licenses.yml` records class-level reuse boundaries. Pending human
  rights review is not an approval. A reviewed registry cannot coexist with
  pending or unresolved license, rights-holder, or access-contact fields in
  the source registry.
- `output_manifest.csv` maps every accepted-paper crosswalk analysis and
  concrete reference or threshold artifact to inputs and comparison behavior.

The `expected_value_or_hash` field in the output manifest is compact JSON with
exactly three keys:

- `artifact_sha256` binds the accepted file;
- `row_count` records the expected number of CSV data rows or is `null` for
  non-CSV files; and
- `checks` records material JSON-path or uniquely selected CSV-field values.

Numerical and JSON-field checks use the manifest row's absolute and relative
tolerances and require at least one material check. A hash-only comparison has
blank tolerance fields and no field checks. Every output row declares exactly
one accepted-paper crosswalk marker.

Run the complete offline validation with:

```bash
make validate-metadata
```

The strict schemas are under `schemas/`. They must use resolvable local
references only; validation never retrieves a schema. The validator fails on
missing or extra registry fields, duplicate IDs, unsafe or symlinked paths,
missing artifacts, hash changes, incomplete column/rights/output/crosswalk
coverage, unresolved references, incompatible types or categorical values,
and misstated live-output reproducibility.
