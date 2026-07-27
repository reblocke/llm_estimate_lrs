from __future__ import annotations

import csv
import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from scripts.validate_contracts import load_contract
from scripts.validate_metadata import (
    STAGE2_REQUIRED_PATHS,
    MetadataValidationError,
    validate_metadata_contracts,
)
from scripts.validate_release import (
    ReleaseValidationError,
    requires_stage2_metadata,
)

ROOT = Path(__file__).resolve().parents[1]


def _copy_contract_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    for directory in ("config", "data", "metadata", "prompts", "results/reference", "schemas"):
        shutil.copytree(ROOT / directory, repository / directory)
    (repository / "docs").mkdir()
    shutil.copy2(
        ROOT / "docs/ACCEPTED_PAPER_CROSSWALK.md",
        repository / "docs/ACCEPTED_PAPER_CROSSWALK.md",
    )
    for relative_path in (
        "ANALYSIS_SPEC.md",
        "DECISIONS.md",
        "EXCEPTIONS.md",
        "KNOWN_ISSUES.md",
        "NNT_LRs_08-26-2025.xlsx",
        "PROJECT.yml",
        "llms-full.txt",
        "nnt_lrs_with_estimated.xlsx",
    ):
        shutil.copy2(ROOT / relative_path, repository / relative_path)
    return repository


def _rewrite_csv(
    path: Path,
    mutation: Callable[[list[str], list[dict[str, str]]], None],
) -> None:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or ())
        rows = list(reader)
    mutation(fields, rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _mutate_matching_row(
    path: Path,
    key: str,
    value: str,
    mutation: Callable[[dict[str, str]], None],
) -> None:
    def apply(_fields: list[str], rows: list[dict[str, str]]) -> None:
        row = next(row for row in rows if row[key] == value)
        mutation(row)

    _rewrite_csv(path, apply)


def _mark_rights_registry_reviewed(repository: Path) -> None:
    path = repository / "metadata/rights_and_licenses.yml"
    rights = yaml.safe_load(path.read_text(encoding="utf-8"))
    rights["review_status"] = "reviewed"
    for record in rights["artifacts"]:
        record.update(
            {
                "license_or_terms": "Reviewed terms",
                "redistribution_decision": "approved",
                "permitted_use_summary": "Reviewed use",
                "attribution_requirement": "Reviewed attribution",
                "approval_authority": "Independent rights reviewer",
                "approval_date": "2026-07-24",
                "unresolved_risk": False,
            }
        )
    path.write_text(yaml.safe_dump(rights, sort_keys=False), encoding="utf-8")


def test_metadata_contracts_validate_complete_repository() -> None:
    summary = validate_metadata_contracts(ROOT)

    assert summary["data_sources"] == 31
    assert summary["variable_dictionary"] == {"datasets": 21, "columns": 255}
    assert summary["output_manifest"] == {"outputs": 17, "crosswalk_rows": 13}
    assert summary["rights"]["artifacts"] == 11
    assert summary["rights"]["review_status"] == "PENDING_HUMAN_RIGHTS_REVIEW"
    assert summary["scientific_documents"]["known_issues"] == 4


def test_data_source_registry_rejects_extra_column(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/data_sources.csv"

    def add_extra(fields: list[str], rows: list[dict[str, str]]) -> None:
        fields.append("unexpected")
        for row in rows:
            row["unexpected"] = "value"

    _rewrite_csv(path, add_extra)

    with pytest.raises(MetadataValidationError, match="wrong columns"):
        validate_metadata_contracts(repository)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda schema: schema["properties"].__setitem__(
                "title",
                {"type": "string", "minLength": -1},
            ),
            "invalid JSON Schema",
        ),
        (
            lambda schema: schema["properties"].__setitem__(
                "title",
                {"$ref": "https://example.invalid/schema.json"},
            ),
            r"non-local \$ref",
        ),
        (
            lambda schema: schema["properties"].__setitem__(
                "title",
                {"$dynamicRef": "https://example.invalid/schema.json"},
            ),
            r"non-local \$dynamicRef",
        ),
        (
            lambda schema: schema["properties"].__setitem__(
                "title",
                {"$ref": "#/$defs/does_not_exist"},
            ),
            "unresolved local schema reference",
        ),
    ],
)
def test_metadata_contract_rejects_invalid_or_external_schema_refs(
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], None],
    message: str,
) -> None:
    repository = _copy_contract_repository(tmp_path)
    schema_path = repository / "schemas/data-source.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    mutation(schema)
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    with pytest.raises(MetadataValidationError, match=message):
        validate_metadata_contracts(repository, schema_root=ROOT)


def test_governance_schemas_control_candidate_metadata_validation(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    schema_path = repository / "schemas/data-source.schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
            }
        ),
        encoding="utf-8",
    )
    _mutate_matching_row(
        repository / "metadata/data_sources.csv",
        "source_id",
        "canonical_analysis_v1",
        lambda row: row.__setitem__("title", ""),
    )

    with pytest.raises(MetadataValidationError, match="schema validation"):
        validate_metadata_contracts(repository, schema_root=ROOT)


def test_data_source_registry_rejects_duplicate_ids(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/data_sources.csv"

    def duplicate(_fields: list[str], rows: list[dict[str, str]]) -> None:
        rows[1]["source_id"] = rows[0]["source_id"]

    _rewrite_csv(path, duplicate)

    with pytest.raises(MetadataValidationError, match="Duplicate data source IDs"):
        validate_metadata_contracts(repository)


def test_data_source_registry_rejects_traversal(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/data_sources.csv"
    _mutate_matching_row(
        path,
        "source_id",
        "canonical_analysis_v1",
        lambda row: row.__setitem__("expected_path", "../outside.csv"),
    )

    with pytest.raises(MetadataValidationError, match="schema validation"):
        validate_metadata_contracts(repository)


@pytest.mark.parametrize("failure", ["missing", "wrong_hash"])
def test_data_source_registry_rejects_missing_or_modified_artifact(
    tmp_path: Path,
    failure: str,
) -> None:
    repository = _copy_contract_repository(tmp_path)
    artifact = repository / "data/curated/diagnostic_lrs_manuscript_v1.csv"
    if failure == "missing":
        artifact.unlink()
        message = "coverage mismatch"
    else:
        path = repository / "metadata/data_sources.csv"
        _mutate_matching_row(
            path,
            "source_id",
            "canonical_analysis_v1",
            lambda row: row.__setitem__("checksum", "0" * 64),
        )
        message = "hash mismatch"

    with pytest.raises(MetadataValidationError, match=message):
        validate_metadata_contracts(repository)


def test_metadata_contract_rejects_symlinked_parent(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    metadata = repository / "metadata"
    real_metadata = repository / "metadata-real"
    metadata.rename(real_metadata)
    metadata.symlink_to(real_metadata, target_is_directory=True)

    with pytest.raises(MetadataValidationError, match="symlinked ancestor"):
        validate_metadata_contracts(repository)


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_variable_dictionary_requires_exact_column_coverage(
    tmp_path: Path,
    mutation: str,
) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/variable_dictionary.csv"

    def mutate(_fields: list[str], rows: list[dict[str, str]]) -> None:
        if mutation == "missing":
            rows.pop()
        else:
            rows.append(dict(rows[0]))

    _rewrite_csv(path, mutate)
    message = "coverage mismatch" if mutation == "missing" else "Duplicate variable dictionary"
    with pytest.raises(MetadataValidationError, match=message):
        validate_metadata_contracts(repository)


def test_variable_dictionary_reconciles_categorical_values(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/variable_dictionary.csv"
    _mutate_matching_row(
        path,
        "column_name",
        "reported_stratum",
        lambda row: row.__setitem__("allowed_values", "LR < 1|LR = 1"),
    )

    with pytest.raises(MetadataValidationError, match="outside the dictionary"):
        validate_metadata_contracts(repository)


def test_variable_dictionary_enforces_declared_data_types(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/variable_dictionary.csv"
    _mutate_matching_row(
        path,
        "column_name",
        "master_row_number",
        lambda row: row.__setitem__("data_type", "boolean"),
    )

    with pytest.raises(MetadataValidationError, match="is not a Boolean"):
        validate_metadata_contracts(repository)


def test_variable_dictionary_enforces_required_nonmissing_values(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/variable_dictionary.csv"
    _mutate_matching_row(
        path,
        "column_name",
        "temperature",
        lambda row: row.__setitem__("required", "true"),
    )

    with pytest.raises(MetadataValidationError, match="Required variable contains blank"):
        validate_metadata_contracts(repository)


def test_rights_registry_requires_every_reviewed_class(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/rights_and_licenses.yml"
    rights = yaml.safe_load(path.read_text(encoding="utf-8"))
    rights["artifacts"] = [
        record for record in rights["artifacts"] if record["rights_id"] != "RIGHTS-PROVIDER-OUTPUTS"
    ]
    path.write_text(yaml.safe_dump(rights, sort_keys=False), encoding="utf-8")

    with pytest.raises(MetadataValidationError, match="Rights class coverage mismatch"):
        validate_metadata_contracts(repository)


def test_rights_registry_requires_accepted_notebook_scope(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/rights_and_licenses.yml"
    rights = yaml.safe_load(path.read_text(encoding="utf-8"))
    rights["artifacts"] = [
        record for record in rights["artifacts"] if record["rights_id"] != "RIGHTS-NOTEBOOKS"
    ]
    path.write_text(yaml.safe_dump(rights, sort_keys=False), encoding="utf-8")

    with pytest.raises(MetadataValidationError, match="Rights class coverage mismatch"):
        validate_metadata_contracts(repository)


def test_rights_registry_rejects_substituted_artifact_scope(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/rights_and_licenses.yml"
    rights = yaml.safe_load(path.read_text(encoding="utf-8"))
    provider = next(
        record for record in rights["artifacts"] if record["rights_id"] == "RIGHTS-PROVIDER-OUTPUTS"
    )
    provider["artifact"] = "data/model_outputs/manuscript_model_outputs_v1.csv"
    path.write_text(yaml.safe_dump(rights, sort_keys=False), encoding="utf-8")

    with pytest.raises(MetadataValidationError, match="Rights class coverage mismatch"):
        validate_metadata_contracts(repository)


def test_rights_registry_does_not_convert_pending_review_to_approval(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/rights_and_licenses.yml"
    rights = yaml.safe_load(path.read_text(encoding="utf-8"))
    pending = next(
        record for record in rights["artifacts"] if record["rights_id"] == "RIGHTS-PROVIDER-OUTPUTS"
    )
    pending["redistribution_decision"] = "approved"
    pending["approval_date"] = "2026-07-24"
    path.write_text(yaml.safe_dump(rights, sort_keys=False), encoding="utf-8")

    with pytest.raises(MetadataValidationError, match="schema validation"):
        validate_metadata_contracts(repository)


def test_rights_registry_rejects_reviewed_status_with_pending_evidence(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/rights_and_licenses.yml"
    rights = yaml.safe_load(path.read_text(encoding="utf-8"))
    rights["review_status"] = "reviewed"
    path.write_text(yaml.safe_dump(rights, sort_keys=False), encoding="utf-8")

    with pytest.raises(MetadataValidationError, match="schema validation"):
        validate_metadata_contracts(repository)


@pytest.mark.parametrize(
    "placeholder",
    [
        "pending external confirmation",
        "unresolved reviewer authority",
        "not assigned",
        "t" "bd",
        "to" "do",
    ],
)
def test_approved_rights_reject_case_insensitive_placeholder_prose(
    tmp_path: Path,
    placeholder: str,
) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/rights_and_licenses.yml"
    rights = yaml.safe_load(path.read_text(encoding="utf-8"))
    approved = next(
        record for record in rights["artifacts"] if record["rights_id"] == "RIGHTS-CODE"
    )
    approved["approval_authority"] = placeholder
    path.write_text(yaml.safe_dump(rights, sort_keys=False), encoding="utf-8")

    with pytest.raises(MetadataValidationError, match="schema validation"):
        validate_metadata_contracts(repository)


def test_approved_rights_reject_placeholder_owner_or_source(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/rights_and_licenses.yml"
    rights = yaml.safe_load(path.read_text(encoding="utf-8"))
    approved = next(
        record for record in rights["artifacts"] if record["rights_id"] == "RIGHTS-CODE"
    )
    approved["owner_or_source"] = "UNKNOWN"
    path.write_text(yaml.safe_dump(rights, sort_keys=False), encoding="utf-8")

    with pytest.raises(MetadataValidationError, match="schema validation"):
        validate_metadata_contracts(repository)


def test_approved_rights_reject_whitespace_only_owner_or_source(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/rights_and_licenses.yml"
    rights = yaml.safe_load(path.read_text(encoding="utf-8"))
    approved = next(
        record for record in rights["artifacts"] if record["rights_id"] == "RIGHTS-CODE"
    )
    approved["owner_or_source"] = "   "
    path.write_text(yaml.safe_dump(rights, sort_keys=False), encoding="utf-8")

    with pytest.raises(MetadataValidationError, match="schema validation"):
        validate_metadata_contracts(repository)


def test_rights_placeholder_policy_allows_legitimate_containing_words(
    tmp_path: Path,
) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/rights_and_licenses.yml"
    rights = yaml.safe_load(path.read_text(encoding="utf-8"))
    approved = next(
        record for record in rights["artifacts"] if record["rights_id"] == "RIGHTS-CODE"
    )
    approved["permitted_use_summary"] = "Use depending on attribution terms"
    path.write_text(yaml.safe_dump(rights, sort_keys=False), encoding="utf-8")

    validate_metadata_contracts(repository)


def test_reviewed_rights_reject_pending_data_source_rights(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    _mark_rights_registry_reviewed(repository)

    with pytest.raises(MetadataValidationError, match="conflicts with pending"):
        validate_metadata_contracts(repository)


def test_data_sources_reject_whitespace_only_rights_evidence(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    _mark_rights_registry_reviewed(repository)
    path = repository / "metadata/data_sources.csv"

    def replace_source_rights(
        _fields: list[str],
        rows: list[dict[str, str]],
    ) -> None:
        for row in rows:
            row["license_or_terms"] = "Reviewed terms"
            row["rights_holder"] = "Reviewed rights holder"
            row["access_contact"] = "Reviewed access contact"
        rows[0]["license_or_terms"] = "   "

    _rewrite_csv(path, replace_source_rights)

    with pytest.raises(MetadataValidationError, match="schema validation"):
        validate_metadata_contracts(repository)


def test_rights_registry_rejects_extra_fields(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/rights_and_licenses.yml"
    rights = yaml.safe_load(path.read_text(encoding="utf-8"))
    rights["artifacts"][0]["unexpected"] = True
    path.write_text(yaml.safe_dump(rights, sort_keys=False), encoding="utf-8")

    with pytest.raises(MetadataValidationError, match="schema validation"):
        validate_metadata_contracts(repository)


def test_output_manifest_rejects_unknown_input_id(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/output_manifest.csv"
    _mutate_matching_row(
        path,
        "output_id",
        "OUT-001",
        lambda row: row.__setitem__("input_artifact_ids", "unknown_artifact"),
    )

    with pytest.raises(MetadataValidationError, match="Unknown input artifact ID"):
        validate_metadata_contracts(repository)


def test_output_manifest_requires_every_accepted_output(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/output_manifest.csv"

    def remove_output(_fields: list[str], rows: list[dict[str, str]]) -> None:
        rows[:] = [row for row in rows if row["output_id"] != "OUT-017"]

    _rewrite_csv(path, remove_output)

    with pytest.raises(MetadataValidationError, match="Accepted output coverage mismatch"):
        validate_metadata_contracts(repository)


def test_output_manifest_verifies_hash_comparisons(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/output_manifest.csv"

    def replace_hash(row: dict[str, str]) -> None:
        expectation = json.loads(row["expected_value_or_hash"])
        expectation["artifact_sha256"] = "0" * 64
        row["expected_value_or_hash"] = json.dumps(
            expectation,
            sort_keys=True,
            separators=(",", ":"),
        )

    _mutate_matching_row(
        path,
        "output_id",
        "OUT-013",
        replace_hash,
    )

    with pytest.raises(MetadataValidationError, match="Output artifact hash mismatch"):
        validate_metadata_contracts(repository)


def test_output_manifest_checks_material_scalar_claims(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/output_manifest.csv"

    def replace_claim(row: dict[str, str]) -> None:
        expectation = json.loads(row["expected_value_or_hash"])
        expectation["checks"][0]["value"] = 999
        row["expected_value_or_hash"] = json.dumps(
            expectation,
            sort_keys=True,
            separators=(",", ":"),
        )

    _mutate_matching_row(path, "output_id", "OUT-001", replace_claim)

    with pytest.raises(MetadataValidationError, match="OUT-001 dataset.rows mismatch"):
        validate_metadata_contracts(repository)


def test_output_manifest_marks_historical_live_output_nonreproducible(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/output_manifest.csv"
    _mutate_matching_row(
        path,
        "output_id",
        "OUT-014",
        lambda row: row.__setitem__("publicly_reproducible", "true"),
    )

    with pytest.raises(MetadataValidationError, match="not publicly reproducible"):
        validate_metadata_contracts(repository)


def test_live_service_classification_cannot_be_hidden_by_descriptive_text(
    tmp_path: Path,
) -> None:
    repository = _copy_contract_repository(tmp_path)
    _mutate_matching_row(
        repository / "metadata/data_sources.csv",
        "source_id",
        "threshold_raw_v1",
        lambda row: (
            row.__setitem__("acquisition_method", "archived local table"),
            row.__setitem__("requires_live_service", "false"),
        ),
    )
    _mutate_matching_row(
        repository / "metadata/output_manifest.csv",
        "output_id",
        "OUT-014",
        lambda row: row.__setitem__("publicly_reproducible", "true"),
    )

    with pytest.raises(MetadataValidationError, match="classification mismatch"):
        validate_metadata_contracts(repository)


def test_live_service_source_ids_cannot_be_rebound_to_local_paths(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/data_sources.csv"

    def swap_live_and_local_ids(
        _fields: list[str],
        rows: list[dict[str, str]],
    ) -> None:
        live = next(row for row in rows if row["source_id"] == "threshold_raw_v1")
        local = next(row for row in rows if row["source_id"] == "threshold_summary_v1")
        live["source_id"] = "threshold_summary_v1"
        live["requires_live_service"] = "false"
        local["source_id"] = "threshold_raw_v1"
        local["requires_live_service"] = "true"

    _rewrite_csv(path, swap_live_and_local_ids)

    with pytest.raises(MetadataValidationError, match="classification mismatch"):
        validate_metadata_contracts(repository)


def test_output_manifest_rejects_comparison_method_suffix_mismatch(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    _mutate_matching_row(
        repository / "metadata/output_manifest.csv",
        "output_id",
        "OUT-002",
        lambda row: row.__setitem__("comparison_method", "json_fields"),
    )

    with pytest.raises(MetadataValidationError, match=r"json_fields requires a json source"):
        validate_metadata_contracts(repository)


def test_output_manifest_requires_semantic_field_checks(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)

    def clear_checks(row: dict[str, str]) -> None:
        expectation = json.loads(row["expected_value_or_hash"])
        expectation["checks"] = []
        row["expected_value_or_hash"] = json.dumps(
            expectation,
            sort_keys=True,
            separators=(",", ":"),
        )

    _mutate_matching_row(
        repository / "metadata/output_manifest.csv",
        "output_id",
        "OUT-001",
        clear_checks,
    )

    with pytest.raises(MetadataValidationError, match="must define field checks"):
        validate_metadata_contracts(repository)


def test_output_manifest_rejects_self_dependency(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    _mutate_matching_row(
        repository / "metadata/output_manifest.csv",
        "output_id",
        "OUT-013",
        lambda row: row.__setitem__("input_artifact_ids", "threshold_cases_v1"),
    )

    with pytest.raises(MetadataValidationError, match="depends on its own output"):
        validate_metadata_contracts(repository)


def test_output_manifest_rejects_indirect_dependency_cycle(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    _mutate_matching_row(
        repository / "metadata/output_manifest.csv",
        "output_id",
        "OUT-013",
        lambda row: row.__setitem__("input_artifact_ids", "threshold_raw_v1"),
    )

    with pytest.raises(MetadataValidationError, match="Output dependency cycle detected"):
        validate_metadata_contracts(repository)


def test_output_comparison_requires_registered_file_format_agreement(
    tmp_path: Path,
) -> None:
    repository = _copy_contract_repository(tmp_path)
    _mutate_matching_row(
        repository / "metadata/data_sources.csv",
        "source_id",
        "reference_main_metrics_v1",
        lambda row: row.__setitem__("file_format", "text"),
    )

    with pytest.raises(MetadataValidationError, match="file format does not match"):
        validate_metadata_contracts(repository)


def test_output_manifest_requires_complete_crosswalk_coverage(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / "metadata/output_manifest.csv"
    _mutate_matching_row(
        path,
        "output_id",
        "OUT-001",
        lambda row: row.__setitem__("notes", "crosswalk:lr-category-distribution"),
    )

    with pytest.raises(MetadataValidationError, match="crosswalk coverage mismatch"):
        validate_metadata_contracts(repository)


def test_each_output_manifest_row_requires_its_own_crosswalk_marker(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    _mutate_matching_row(
        repository / "metadata/output_manifest.csv",
        "output_id",
        "OUT-017",
        lambda row: row.__setitem__("notes", "offline summary"),
    )

    with pytest.raises(MetadataValidationError, match="exactly one crosswalk marker"):
        validate_metadata_contracts(repository)


@pytest.mark.parametrize(
    ("relative_path", "old", "new", "message"),
    [
        (
            "ANALYSIS_SPEC.md",
            "## Randomness contract",
            "## Randomness notes",
            "missing required heading",
        ),
        (
            "ANALYSIS_SPEC.md",
            "GPT-4o;\n2. GPT-5;\n3. o3.",
            "GPT-4o;\n2. o3;\n3. GPT-5.",
            "missing required contract text",
        ),
        (
            "KNOWN_ISSUES.md",
            "1.0326838754",
            "1.03",
            "missing frozen evidence-direction value",
        ),
    ],
)
def test_scientific_documents_require_frozen_contract_details(
    tmp_path: Path,
    relative_path: str,
    old: str,
    new: str,
    message: str,
) -> None:
    repository = _copy_contract_repository(tmp_path)
    path = repository / relative_path
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

    with pytest.raises(MetadataValidationError, match=message):
        validate_metadata_contracts(repository)


def test_project_metadata_points_to_pending_rights_registry(tmp_path: Path) -> None:
    repository = _copy_contract_repository(tmp_path)
    project_path = repository / "PROJECT.yml"
    project = yaml.safe_load(project_path.read_text(encoding="utf-8"))
    project["data"]["rights_registry"] = "PENDING_HUMAN_ASSIGNMENT"
    project_path.write_text(yaml.safe_dump(project, sort_keys=False), encoding="utf-8")

    with pytest.raises(MetadataValidationError, match="must point"):
        validate_metadata_contracts(repository)


def test_smoke_and_audit_include_metadata_without_live_paths() -> None:
    for target in ("smoke", "audit"):
        dry_run = subprocess.run(
            ["make", "-n", target],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        assert "scripts/validate_metadata.py" in dry_run.stdout
        assert "scripts/run_replication.py" not in dry_run.stdout
        assert "uv sync" not in dry_run.stdout


def test_historical_v1_contract_does_not_require_post_release_metadata() -> None:
    contract = load_contract("release/contracts/v1.0.0.json", ROOT)

    assert requires_stage2_metadata(contract) is False


def test_future_contract_must_declare_complete_stage2_set() -> None:
    contract = {
        "release_ref": "v2.0.0",
        "audited_commit": "b" * 40,
        "required_paths": [],
    }
    with pytest.raises(ReleaseValidationError, match="Every successor"):
        requires_stage2_metadata(contract)

    contract["required_paths"] = ["ANALYSIS_SPEC.md"]
    with pytest.raises(ReleaseValidationError, match="Every successor"):
        requires_stage2_metadata(contract)

    contract["required_paths"] = sorted(STAGE2_REQUIRED_PATHS)
    assert requires_stage2_metadata(contract) is True
