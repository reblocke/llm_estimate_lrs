#!/usr/bin/env python3
"""Validate scientific, data, rights, and accepted-output metadata offline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import stat
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn
from urllib.parse import urlparse

import jsonschema
import yaml
from referencing import Registry, Resource
from referencing.exceptions import (
    CannotDetermineSpecification,
    NoSuchResource,
    Unresolvable,
)

ROOT = Path(__file__).resolve().parents[1]

DATA_SOURCE_FIELDS = (
    "source_id",
    "title",
    "provider",
    "citation",
    "version_or_access_date",
    "persistent_identifier",
    "access_class",
    "license_or_terms",
    "rights_holder",
    "included_in_package",
    "acquisition_method",
    "requires_live_service",
    "expected_path",
    "file_format",
    "checksum_algorithm",
    "checksum",
    "sensitivity",
    "contains_identifiers",
    "retention_rule",
    "access_contact",
    "notes",
)

VARIABLE_DICTIONARY_FIELDS = (
    "dataset_id",
    "column_name",
    "display_name",
    "description",
    "data_type",
    "unit",
    "allowed_values",
    "missing_value_meaning",
    "source_or_derivation",
    "analysis_role",
    "sensitivity",
    "required",
    "notes",
)

OUTPUT_MANIFEST_FIELDS = (
    "output_id",
    "publication_location",
    "description",
    "claim_type",
    "producer",
    "function_or_section",
    "input_artifact_ids",
    "output_file",
    "seed",
    "expected_value_or_hash",
    "comparison_method",
    "absolute_tolerance",
    "relative_tolerance",
    "required",
    "publicly_reproducible",
    "restricted_requirements",
    "status",
    "notes",
)

REQUIRED_ANALYSIS_SPEC_HEADINGS = (
    "# Analysis specification",
    "## Authority and change control",
    "## Scientific question",
    "## Unit of analysis and population",
    "## Source-data construction",
    "## Inclusion, exclusion, repeated rows, and missingness",
    "## Reported-LR transformation",
    "## Model configurations and prompts",
    "## Primary estimand and comparison direction",
    "## Agreement analysis",
    "## Pairwise comparisons",
    "## Evidence-direction analysis",
    "## Calibration analysis",
    "## Inverse reliability analysis",
    "## Qualitative agreement",
    "## Reliability zones",
    "## Laboratory-discrepancy analysis",
    "## Threshold sensitivity analysis",
    "## Randomness contract",
    "## Numerical tolerances",
    "## Diagnostics and assumptions",
    "## Prespecified, exploratory, and descriptive analyses",
    "## Known deviations and issues",
    "## Interpretation and safety limitations",
    "## Version history and approvals",
)

REQUIRED_RIGHTS_ARTIFACTS = {
    "RIGHTS-ARTICLE-TEXT": "llms-full.txt",
    "RIGHTS-AUTHOR-CURATION": (
        "data/curated/diagnostic_lrs_manuscript_v1.csv::author_curated_fields;"
        "data/provenance/**"
    ),
    "RIGHTS-CANONICAL-EXPORTS": "data/curated/**;data/provenance/**",
    "RIGHTS-CODE": "scripts/**;tests/**",
    "RIGHTS-LITERATURE-VALUES": (
        "data/curated/diagnostic_lrs_manuscript_v1.csv::lr_raw;"
        "data/curated/diagnostic_lrs_manuscript_v1.csv::lr_reported"
    ),
    "RIGHTS-NOTEBOOKS": (
        "data_analysis.ipynb;"
        "supplementary_analyses.ipynb;"
        "lr_scraper_estimator.ipynb;"
        "threshold_perturbation_sensitivity_analysis.ipynb"
    ),
    "RIGHTS-PROMPTS": "prompts/**",
    "RIGHTS-PROVIDER-OUTPUTS": "data/model_outputs/**",
    "RIGHTS-REFERENCE-OUTPUTS": "results/reference/**",
    "RIGHTS-RELEASE-ASSETS": "generated:dist/**",
    "RIGHTS-WORKBOOKS": "NNT_LRs_08-26-2025.xlsx;nnt_lrs_with_estimated.xlsx",
}

STAGE2_SCHEMA_PATHS = {
    "schemas/data-source.schema.json",
    "schemas/output-manifest.schema.json",
    "schemas/rights-and-licenses.schema.json",
    "schemas/variable-dictionary.schema.json",
}

STAGE2_REQUIRED_PATHS = {
    "ANALYSIS_SPEC.md",
    "DECISIONS.md",
    "EXCEPTIONS.md",
    "KNOWN_ISSUES.md",
    "metadata/data_sources.csv",
    "metadata/output_manifest.csv",
    "metadata/rights_and_licenses.yml",
    "metadata/variable_dictionary.csv",
    *STAGE2_SCHEMA_PATHS,
}

LIVE_SERVICE_SOURCES = {
    "auxiliary_gpt41_outputs_v1": "data/model_outputs/auxiliary_gpt-4.1_outputs_v1.csv",
    "manuscript_model_outputs_v1": "data/model_outputs/manuscript_model_outputs_v1.csv",
    "threshold_raw_v1": (
        "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_raw.csv"
    ),
}

FILE_FORMAT_SUFFIXES = {
    "csv": {".csv"},
    "json": {".json"},
    "text": {".md", ".txt"},
    "xlsx": {".xlsx"},
}

REVIEW_PLACEHOLDER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:pending|unresolved|unknown|t"
    r"bd|to"
    r"do|unassigned|"
    r"not[\s_-]+assigned)(?![A-Za-z0-9])",
    flags=re.IGNORECASE,
)

ACCEPTED_OUTPUT_PATHS = {
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_cases.csv",
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_raw.csv",
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_reviewer_table.csv",
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_summary.csv",
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_summary.md",
}


class MetadataValidationError(RuntimeError):
    """Raised when a scientific or metadata contract is invalid."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MetadataValidationError(message)


def _reject_external_schema_refs(
    value: Any,
    label: str,
    location: str = "<root>",
) -> None:
    if isinstance(value, dict):
        require(
            "$id" not in value,
            f"{label} contains unsupported embedded schema identity at {location}",
        )
        for keyword in ("$ref", "$dynamicRef"):
            if keyword in value:
                reference = value[keyword]
                require(
                    isinstance(reference, str) and reference.startswith("#"),
                    f"{label} contains a non-local {keyword} at "
                    f"{location}: {reference!r}",
                )
        for key, child in value.items():
            _reject_external_schema_refs(child, label, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_external_schema_refs(child, label, f"{location}[{index}]")


def _local_schema_refs(value: Any) -> list[str]:
    references: list[str] = []
    if isinstance(value, dict):
        references.extend(
            reference
            for keyword in ("$ref", "$dynamicRef")
            if isinstance((reference := value.get(keyword)), str)
        )
        for child in value.values():
            references.extend(_local_schema_refs(child))
    elif isinstance(value, list):
        for child in value:
            references.extend(_local_schema_refs(child))
    return references


def _validate_schema_document(schema: Any, label: str) -> dict[str, Any]:
    require(isinstance(schema, dict), f"{label} must contain a JSON object")
    require(
        schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema",
        f"{label} must declare JSON Schema draft 2020-12",
    )
    _reject_external_schema_refs(schema, label)
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise MetadataValidationError(f"{label} uses an invalid JSON Schema: {exc.message}") from exc
    base_uri = f"urn:llm-estimate-lrs:schema:{hashlib.sha256(label.encode()).hexdigest()}"
    try:
        resource = Resource.from_contents(schema)
        resolver = (
            Registry(retrieve=_deny_schema_retrieval)
            .with_resource(base_uri, resource)
            .crawl()
            .resolver(base_uri)
        )
        for reference in _local_schema_refs(schema):
            resolver.lookup(reference)
    except (CannotDetermineSpecification, NoSuchResource, Unresolvable) as exc:
        raise MetadataValidationError(
            f"{label} contains an unresolved local schema reference: {exc}"
        ) from exc
    return schema


def _load_schema(repository: Path, relative_path: str) -> dict[str, Any]:
    path = _require_regular_file(repository, relative_path)
    schema = json.loads(path.read_text(encoding="utf-8"))
    return _validate_schema_document(schema, relative_path)


def _deny_schema_retrieval(uri: str) -> NoReturn:
    raise NoSuchResource(ref=uri)


def _validate_schema(instance: Any, schema: dict[str, Any], label: str) -> None:
    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
        registry=Registry(retrieve=_deny_schema_retrieval),
    )
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = ".".join(str(item) for item in first.path) or "<root>"
        raise MetadataValidationError(f"{label} failed schema validation at {location}: {first.message}")


def _safe_relative_path(raw_path: str, label: str) -> PurePosixPath:
    require(bool(raw_path), f"{label} must not be empty")
    require("\\" not in raw_path, f"{label} must use POSIX separators: {raw_path}")
    relative = PurePosixPath(raw_path)
    require(not relative.is_absolute(), f"{label} must be relative: {raw_path}")
    require(
        all(part not in {"", ".", ".."} for part in relative.parts),
        f"{label} contains an unsafe path component: {raw_path}",
    )
    require(not re.match(r"^[A-Za-z]:", raw_path), f"{label} must not use a drive path: {raw_path}")
    return relative


def _require_regular_file(repository: Path, relative_path: str) -> Path:
    relative = _safe_relative_path(relative_path, "Metadata path")
    current = repository
    for index, part in enumerate(relative.parts):
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError as exc:
            raise MetadataValidationError(f"Missing metadata artifact: {relative_path}") from exc
        if index < len(relative.parts) - 1:
            require(
                stat.S_ISDIR(mode) and not stat.S_ISLNK(mode),
                f"Metadata path has a non-directory or symlinked ancestor: "
                f"{current.relative_to(repository).as_posix()}",
            )
        else:
            require(
                stat.S_ISREG(mode) and not stat.S_ISLNK(mode),
                f"Metadata artifact is not a regular file: {relative_path}",
            )
    return current


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_csv(
    repository: Path,
    relative_path: str,
    fields: tuple[str, ...],
    schema_name: str,
    *,
    schema_root: Path | None = None,
) -> list[dict[str, str]]:
    path = _require_regular_file(repository, relative_path)
    schema = _load_schema(schema_root or repository, f"schemas/{schema_name}")
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            require(
                tuple(reader.fieldnames or ()) == fields,
                f"{relative_path} has the wrong columns or column order",
            )
            rows = list(reader)
    except (csv.Error, UnicodeDecodeError) as exc:
        raise MetadataValidationError(f"Could not parse {relative_path}: {exc}") from exc
    require(bool(rows), f"{relative_path} must contain at least one data row")
    for index, row in enumerate(rows, start=2):
        require(None not in row, f"{relative_path}:{index} contains an extra CSV field")
        _validate_schema(row, schema, f"{relative_path}:{index}")
    return rows


def _duplicates(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def _registered_artifact_paths(repository: Path) -> set[str]:
    paths = {
        "NNT_LRs_08-26-2025.xlsx",
        "nnt_lrs_with_estimated.xlsx",
        "llms-full.txt",
    }
    for base, suffixes in (
        ("config", {".json"}),
        ("prompts", {".json"}),
        ("data", {".csv", ".json"}),
        ("results/reference", {".csv", ".json"}),
    ):
        directory = repository / base
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix in suffixes:
                paths.add(path.relative_to(repository).as_posix())
    paths.add("data/model_outputs/threshold_perturbation_v1/threshold_perturbation_summary.md")
    return paths


def validate_data_sources(
    repository: Path = ROOT,
    *,
    schema_root: Path | None = None,
) -> dict[str, dict[str, str]]:
    rows = _load_csv(
        repository,
        "metadata/data_sources.csv",
        DATA_SOURCE_FIELDS,
        "data-source.schema.json",
        schema_root=schema_root,
    )
    ids = [row["source_id"] for row in rows]
    paths = [row["expected_path"] for row in rows]
    require(not _duplicates(ids), f"Duplicate data source IDs: {_duplicates(ids)}")
    require(not _duplicates(paths), f"Duplicate registered artifact paths: {_duplicates(paths)}")
    observed_paths = set(paths)
    expected_paths = _registered_artifact_paths(repository)
    require(
        observed_paths == expected_paths,
        "Data source coverage mismatch; "
        f"missing={sorted(expected_paths - observed_paths)}, "
        f"unexpected={sorted(observed_paths - expected_paths)}",
    )
    observed_live_sources = {
        row["source_id"]: row["expected_path"]
        for row in rows
        if row["requires_live_service"] == "true"
    }
    require(
        observed_live_sources == LIVE_SERVICE_SOURCES,
        "Live-service source classification mismatch; "
        f"expected={LIVE_SERVICE_SOURCES}, observed={observed_live_sources}",
    )
    for row in rows:
        path = _require_regular_file(repository, row["expected_path"])
        require(
            path.suffix in FILE_FORMAT_SUFFIXES[row["file_format"]],
            f"Data source file format does not match its path: {row['source_id']}",
        )
        observed_hash = _sha256(path)
        require(
            observed_hash == row["checksum"],
            f"Data source hash mismatch for {row['source_id']}: "
            f"expected {row['checksum']}, observed {observed_hash}",
        )
    return {row["source_id"]: row for row in rows}


def _public_csv_paths(repository: Path) -> list[str]:
    paths = [
        *(repository / "data").rglob("*.csv"),
        *(repository / "results/reference").rglob("*.csv"),
    ]
    return sorted(path.relative_to(repository).as_posix() for path in paths)


def _validate_typed_value(value: str, data_type: str, label: str) -> None:
    if data_type == "string":
        return
    if data_type == "boolean":
        require(value.casefold() in {"true", "false"}, f"{label} is not a Boolean: {value}")
        return
    if data_type == "integer":
        try:
            int(value)
        except ValueError as exc:
            raise MetadataValidationError(f"{label} is not an integer: {value}") from exc
        return
    if data_type == "number":
        try:
            number = float(value)
        except ValueError as exc:
            raise MetadataValidationError(f"{label} is not numeric: {value}") from exc
        require(math.isfinite(number), f"{label} is not finite: {value}")
        return
    if data_type == "date":
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise MetadataValidationError(f"{label} is not an ISO-8601 date: {value}") from exc
        return
    if data_type == "datetime":
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MetadataValidationError(f"{label} is not an ISO-8601 datetime: {value}") from exc
        return
    if data_type == "uri":
        parsed = urlparse(value)
        require(
            parsed.scheme in {"https", "http"} and bool(parsed.netloc),
            f"{label} is not an HTTP(S) URI: {value}",
        )
        return
    raise MetadataValidationError(f"{label} declares an unsupported data type: {data_type}")


def validate_variable_dictionary(
    sources: dict[str, dict[str, str]],
    repository: Path = ROOT,
    *,
    schema_root: Path | None = None,
) -> dict[str, int]:
    rows = _load_csv(
        repository,
        "metadata/variable_dictionary.csv",
        VARIABLE_DICTIONARY_FIELDS,
        "variable-dictionary.schema.json",
        schema_root=schema_root,
    )
    keys = [(row["dataset_id"], row["column_name"]) for row in rows]
    duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
    require(not duplicates, f"Duplicate variable dictionary entries: {duplicates}")

    public_csvs = _public_csv_paths(repository)
    registered_csvs = {
        row["expected_path"]: source_id
        for source_id, row in sources.items()
        if row["file_format"] == "csv"
    }
    require(
        set(public_csvs) == set(registered_csvs),
        "Every public CSV must resolve to exactly one data source record",
    )

    expected_keys: set[tuple[str, str]] = set()
    values_by_key: dict[tuple[str, str], list[str]] = {}
    for relative_path in public_csvs:
        path = _require_regular_file(repository, relative_path)
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            header = list(reader.fieldnames or ())
            if not header:
                raise MetadataValidationError(f"Public CSV is empty: {relative_path}")
            records = list(reader)
        require(len(header) == len(set(header)), f"Public CSV has duplicate columns: {relative_path}")
        dataset_id = registered_csvs[relative_path]
        for column in header:
            key = (dataset_id, column)
            expected_keys.add(key)
            values_by_key[key] = [record[column] for record in records]
    observed_keys = set(keys)
    require(
        observed_keys == expected_keys,
        "Variable dictionary coverage mismatch; "
        f"missing={sorted(expected_keys - observed_keys)}, "
        f"unexpected={sorted(observed_keys - expected_keys)}",
    )

    for row in rows:
        key = (row["dataset_id"], row["column_name"])
        values = values_by_key[key]
        blanks = [value for value in values if value == ""]
        if row["required"] == "true":
            require(
                not blanks,
                f"Required variable contains blank values: {row['dataset_id']}.{row['column_name']}",
            )
        for value in values:
            if value != "":
                _validate_typed_value(
                    value,
                    row["data_type"],
                    f"{row['dataset_id']}.{row['column_name']}",
                )
        allowed = row["allowed_values"]
        if not allowed:
            continue
        allowed_values = set(allowed.split("|"))
        observed = {value for value in values if value != ""}
        if row["data_type"] == "boolean":
            observed = {value.casefold() for value in observed}
            allowed_values = {value.casefold() for value in allowed_values}
        require(
            observed <= allowed_values,
            f"Observed values are outside the dictionary for "
            f"{row['dataset_id']}.{row['column_name']}: {sorted(observed - allowed_values)}",
        )
    return {
        "datasets": len(public_csvs),
        "columns": len(rows),
    }


def validate_rights_registry(
    repository: Path = ROOT,
    *,
    schema_root: Path | None = None,
) -> dict[str, Any]:
    path = _require_regular_file(repository, "metadata/rights_and_licenses.yml")
    schema = _load_schema(
        schema_root or repository,
        "schemas/rights-and-licenses.schema.json",
    )
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise MetadataValidationError(f"Invalid rights registry YAML: {exc}") from exc
    _validate_schema(document, schema, "metadata/rights_and_licenses.yml")
    artifacts = document["artifacts"]
    ids = [record["rights_id"] for record in artifacts]
    require(not _duplicates(ids), f"Duplicate rights IDs: {_duplicates(ids)}")
    observed_artifacts = {record["rights_id"]: record["artifact"] for record in artifacts}
    changed_artifacts = sorted(
        rights_id
        for rights_id in set(observed_artifacts) & set(REQUIRED_RIGHTS_ARTIFACTS)
        if observed_artifacts[rights_id] != REQUIRED_RIGHTS_ARTIFACTS[rights_id]
    )
    require(
        observed_artifacts == REQUIRED_RIGHTS_ARTIFACTS,
        "Rights class coverage mismatch; "
        f"missing={sorted(set(REQUIRED_RIGHTS_ARTIFACTS) - set(observed_artifacts))}, "
        f"unexpected={sorted(set(observed_artifacts) - set(REQUIRED_RIGHTS_ARTIFACTS))}, "
        f"changed={changed_artifacts}",
    )
    approval_fields = (
        "owner_or_source",
        "license_or_terms",
        "permitted_use_summary",
        "attribution_requirement",
        "approval_authority",
    )
    for record in artifacts:
        for artifact in record["artifact"].split(";"):
            if artifact.startswith("generated:"):
                _safe_relative_path(artifact.removeprefix("generated:").replace("**", "placeholder"), "Rights path")
                continue
            base_path = artifact.split("::", maxsplit=1)[0].replace("**", "placeholder")
            _safe_relative_path(base_path, "Rights path")
        if record["redistribution_decision"] == "pending":
            require(
                "pending_human" in record["license_or_terms"].casefold()
                or "pending_human" in record["approval_authority"].casefold(),
                f"Pending rights record lacks an explicit human-review marker: {record['rights_id']}",
            )
        if record["redistribution_decision"] == "approved":
            require(
                record["approval_date"] is not None
                and not record["unresolved_risk"]
                and all(
                    bool(record[field].strip())
                    and REVIEW_PLACEHOLDER_RE.search(record[field]) is None
                    for field in approval_fields
                ),
                f"Approved rights record retains pending or unresolved evidence: "
                f"{record['rights_id']}",
            )
        if document["review_status"] == "reviewed":
            require(
                record["redistribution_decision"] != "pending"
                and not record["unresolved_risk"]
                and all(
                    bool(record[field].strip())
                    and REVIEW_PLACEHOLDER_RE.search(record[field]) is None
                    for field in approval_fields
                ),
                f"Reviewed rights registry retains pending or unresolved evidence: "
                f"{record['rights_id']}",
            )
    return {
        "artifacts": len(artifacts),
        "review_status": document["review_status"],
    }


def validate_reviewed_source_rights(
    sources: dict[str, dict[str, str]],
    rights: dict[str, Any],
) -> None:
    if rights["review_status"] != "reviewed":
        return
    source_rights_fields = (
        "license_or_terms",
        "rights_holder",
        "access_contact",
    )
    unresolved = sorted(
        f"{source_id}.{field}"
        for source_id, source in sources.items()
        for field in source_rights_fields
        if not source[field].strip()
        or REVIEW_PLACEHOLDER_RE.search(source[field]) is not None
    )
    require(
        not unresolved,
        "Reviewed rights registry conflicts with pending or unresolved data-source "
        f"rights fields: {unresolved}",
    )


def _slug(value: str) -> str:
    value = value.casefold().replace("–", "-").replace("—", "-")
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def _crosswalk_slugs(repository: Path) -> set[str]:
    path = _require_regular_file(repository, "docs/ACCEPTED_PAPER_CROSSWALK.md")
    rows: list[str] = []
    in_table = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("| Result |"):
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells and cells[0] and not set(cells[0]) <= {"-", ":"}:
            rows.append(_slug(cells[0]))
    require(bool(rows), "Accepted-paper crosswalk table is empty or unavailable")
    return set(rows)


def _expected_output_contract(row: dict[str, str]) -> dict[str, Any]:
    try:
        contract = json.loads(row["expected_value_or_hash"])
    except json.JSONDecodeError as exc:
        raise MetadataValidationError(
            f"Output expectation is not valid JSON: {row['output_id']}"
        ) from exc
    require(isinstance(contract, dict), f"Output expectation must be an object: {row['output_id']}")
    require(
        set(contract) == {"artifact_sha256", "row_count", "checks"},
        f"Output expectation has the wrong fields: {row['output_id']}",
    )
    require(
        isinstance(contract["artifact_sha256"], str)
        and re.fullmatch(r"[0-9a-f]{64}", contract["artifact_sha256"]) is not None,
        f"Output expectation has an invalid artifact SHA-256: {row['output_id']}",
    )
    require(
        contract["row_count"] is None
        or (
            isinstance(contract["row_count"], int)
            and not isinstance(contract["row_count"], bool)
            and contract["row_count"] >= 0
        ),
        f"Output expectation has an invalid row count: {row['output_id']}",
    )
    require(isinstance(contract["checks"], list), f"Output checks must be a list: {row['output_id']}")
    return contract


def _compare_expected_value(
    observed: Any,
    expected: Any,
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
    label: str,
) -> None:
    if isinstance(expected, bool | str):
        require(observed == expected, f"{label} mismatch: expected {expected!r}, observed {observed!r}")
        return
    require(
        isinstance(expected, int | float) and not isinstance(expected, bool),
        f"{label} has an unsupported expected value",
    )
    try:
        observed_number = float(observed)
    except (TypeError, ValueError) as exc:
        raise MetadataValidationError(f"{label} is not numeric: {observed!r}") from exc
    expected_number = float(expected)
    require(
        math.isfinite(observed_number) and math.isfinite(expected_number),
        f"{label} contains a non-finite numeric value",
    )
    tolerance = absolute_tolerance + relative_tolerance * abs(expected_number)
    require(
        abs(observed_number - expected_number) <= tolerance,
        f"{label} mismatch: expected {expected_number}, observed {observed_number}, tolerance {tolerance}",
    )


def _json_path(document: Any, raw_path: str, output_id: str) -> Any:
    require(
        re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", raw_path) is not None,
        f"Invalid JSON expectation path in {output_id}: {raw_path}",
    )
    current = document
    for part in raw_path.split("."):
        require(isinstance(current, dict) and part in current, f"Missing JSON path in {output_id}: {raw_path}")
        current = current[part]
    return current


def _validate_output_expectations(
    row: dict[str, str],
    output_path: Path,
    contract: dict[str, Any],
) -> None:
    require(
        _sha256(output_path) == contract["artifact_sha256"],
        f"Output artifact hash mismatch: {row['output_id']}",
    )
    absolute_tolerance = float(row["absolute_tolerance"] or 0)
    relative_tolerance = float(row["relative_tolerance"] or 0)

    if output_path.suffix == ".csv":
        with output_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            records = list(reader)
        require(
            contract["row_count"] == len(records),
            f"Output row count mismatch for {row['output_id']}: "
            f"expected {contract['row_count']}, observed {len(records)}",
        )
        for check in contract["checks"]:
            require(
                isinstance(check, dict) and set(check) == {"where", "field", "value"},
                f"CSV output check has the wrong fields: {row['output_id']}",
            )
            where = check["where"]
            require(
                isinstance(where, dict)
                and bool(where)
                and all(isinstance(key, str) and isinstance(value, str) for key, value in where.items()),
                f"CSV output selector is invalid: {row['output_id']}",
            )
            matches = [
                record
                for record in records
                if all(record.get(key) == value for key, value in where.items())
            ]
            require(
                len(matches) == 1,
                f"CSV output selector must resolve exactly one row in {row['output_id']}: {where}",
            )
            field = check["field"]
            require(
                isinstance(field, str) and field in matches[0],
                f"CSV output check uses an unknown field in {row['output_id']}: {field}",
            )
            _compare_expected_value(
                matches[0][field],
                check["value"],
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
                label=f"{row['output_id']} {where}.{field}",
            )
        return

    require(contract["row_count"] is None, f"Non-CSV output must use a null row count: {row['output_id']}")
    if output_path.suffix == ".json":
        document = json.loads(output_path.read_text(encoding="utf-8"))
        for check in contract["checks"]:
            require(
                isinstance(check, dict) and set(check) == {"path", "value"},
                f"JSON output check has the wrong fields: {row['output_id']}",
            )
            path = check["path"]
            require(isinstance(path, str), f"JSON output check path is invalid: {row['output_id']}")
            _compare_expected_value(
                _json_path(document, path, row["output_id"]),
                check["value"],
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
                label=f"{row['output_id']} {path}",
            )
        return

    require(
        not contract["checks"],
        f"Non-CSV and non-JSON output may define only a hash: {row['output_id']}",
    )


def _validate_output_dependency_graph(
    rows: list[dict[str, str]],
    sources: dict[str, dict[str, str]],
) -> None:
    source_id_by_path = {
        source["expected_path"]: source_id for source_id, source in sources.items()
    }
    output_source_ids = {
        source_id_by_path[row["output_file"]]
        for row in rows
    }
    dependencies = {
        source_id_by_path[row["output_file"]]: {
            source_id
            for source_id in row["input_artifact_ids"].split(";")
            if source_id in output_source_ids
        }
        for row in rows
    }
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(source_id: str) -> None:
        if source_id in visited:
            return
        if source_id in visiting:
            cycle_start = visiting.index(source_id)
            cycle = [*visiting[cycle_start:], source_id]
            raise MetadataValidationError(
                f"Output dependency cycle detected: {' -> '.join(cycle)}"
            )
        visiting.append(source_id)
        for dependency in sorted(dependencies[source_id]):
            visit(dependency)
        visiting.pop()
        visited.add(source_id)

    for source_id in sorted(dependencies):
        visit(source_id)


def validate_output_manifest(
    sources: dict[str, dict[str, str]],
    repository: Path = ROOT,
    *,
    schema_root: Path | None = None,
) -> dict[str, int]:
    rows = _load_csv(
        repository,
        "metadata/output_manifest.csv",
        OUTPUT_MANIFEST_FIELDS,
        "output-manifest.schema.json",
        schema_root=schema_root,
    )
    ids = [row["output_id"] for row in rows]
    paths = [row["output_file"] for row in rows]
    require(not _duplicates(ids), f"Duplicate output IDs: {_duplicates(ids)}")
    require(not _duplicates(paths), f"Duplicate output files: {_duplicates(paths)}")
    source_paths = {row["expected_path"] for row in sources.values()}
    source_ids = set(sources)
    for row in rows:
        input_source_ids = row["input_artifact_ids"].split(";")
        for source_id in input_source_ids:
            require(source_id in source_ids, f"Unknown input artifact ID in {row['output_id']}: {source_id}")
            require(
                sources[source_id]["expected_path"] != row["output_file"],
                f"Output manifest row depends on its own output artifact: {row['output_id']}",
            )
        require(
            row["output_file"] in source_paths,
            f"Output file is not registered as an artifact: {row['output_file']}",
        )
        output_source = next(
            source for source in sources.values() if source["expected_path"] == row["output_file"]
        )
        output_path = _require_regular_file(repository, row["output_file"])
        require(
            output_path.suffix in FILE_FORMAT_SUFFIXES[output_source["file_format"]],
            f"Output source format does not match its file suffix: {row['output_id']}",
        )
        if output_source["requires_live_service"] == "true":
            require(
                row["publicly_reproducible"] == "false"
                and row["restricted_requirements"] != "none",
                f"Historical live-query output must disclose that it is not publicly reproducible: "
                f"{row['output_id']}",
            )
        expectation = _expected_output_contract(row)
        if row["comparison_method"] == "sha256":
            require(
                row["absolute_tolerance"] == "" and row["relative_tolerance"] == "",
                f"Hash comparison must not define numeric tolerances: {row['output_id']}",
            )
            require(not expectation["checks"], f"Hash-only output must not define field checks: {row['output_id']}")
        else:
            expected_suffix = {
                "numeric_table": ".csv",
                "json_fields": ".json",
            }[row["comparison_method"]]
            expected_format = {
                "numeric_table": "csv",
                "json_fields": "json",
            }[row["comparison_method"]]
            require(
                output_path.suffix == expected_suffix
                and output_source["file_format"] == expected_format,
                f"Comparison method {row['comparison_method']} requires a "
                f"{expected_format} source and {expected_suffix} output: "
                f"{row['output_id']}",
            )
            require(
                row["absolute_tolerance"] != "" and row["relative_tolerance"] != "",
                f"Numeric or semantic comparison lacks tolerances: {row['output_id']}",
            )
            require(
                bool(expectation["checks"]),
                f"Numeric or semantic comparison must define field checks: {row['output_id']}",
            )
        _validate_output_expectations(row, output_path, expectation)

    _validate_output_dependency_graph(rows, sources)

    expected_outputs = {
        path.relative_to(repository).as_posix()
        for path in (repository / "results/reference").iterdir()
        if path.suffix in {".csv", ".json"}
    } | ACCEPTED_OUTPUT_PATHS
    require(
        set(paths) == expected_outputs,
        "Accepted output coverage mismatch; "
        f"missing={sorted(expected_outputs - set(paths))}, "
        f"unexpected={sorted(set(paths) - expected_outputs)}",
    )

    expected_crosswalk = _crosswalk_slugs(repository)
    observed_crosswalk: Counter[str] = Counter()
    for row in rows:
        markers = [
            marker.removeprefix("crosswalk:")
            for marker in row["notes"].split(";")
            if marker.startswith("crosswalk:")
        ]
        require(
            len(markers) == 1,
            f"Each output manifest row must declare exactly one crosswalk marker: "
            f"{row['output_id']}",
        )
        require(
            markers[0] in expected_crosswalk,
            f"Output manifest row uses an unknown crosswalk marker: "
            f"{row['output_id']} ({markers[0]})",
        )
        observed_crosswalk[markers[0]] += 1
    require(
        set(observed_crosswalk) == expected_crosswalk,
        "Accepted crosswalk coverage mismatch; "
        f"missing={sorted(expected_crosswalk - set(observed_crosswalk))}, "
        f"unexpected={sorted(set(observed_crosswalk) - expected_crosswalk)}",
    )
    return {
        "outputs": len(rows),
        "crosswalk_rows": len(expected_crosswalk),
    }


def _register_ids(path: Path, pattern: str, label: str) -> list[str]:
    text = path.read_text(encoding="utf-8")
    ids = re.findall(pattern, text, flags=re.MULTILINE)
    require(bool(ids), f"{label} has no stable IDs")
    require(not _duplicates(ids), f"{label} has duplicate stable IDs: {_duplicates(ids)}")
    return ids


def validate_scientific_documents(repository: Path = ROOT) -> dict[str, int]:
    analysis_path = _require_regular_file(repository, "ANALYSIS_SPEC.md")
    text = analysis_path.read_text(encoding="utf-8")
    positions = []
    for heading in REQUIRED_ANALYSIS_SPEC_HEADINGS:
        position = text.find(heading)
        require(position >= 0, f"ANALYSIS_SPEC.md is missing required heading: {heading}")
        positions.append(position)
    require(positions == sorted(positions), "ANALYSIS_SPEC.md headings are out of required order")
    require("**Specification ID:** `analysis-spec-v1`" in text, "ANALYSIS_SPEC.md has the wrong ID")
    require(
        "**Status:** draft pending independent statistical review" in text,
        "ANALYSIS_SPEC.md must remain draft pending independent statistical review",
    )
    required_fragments = (
        "log(LR_reported) - log(LR_model)",
        "`numpy.random.default_rng(20260407)`",
        "2,000 bootstrap",
        "GPT-4o;\n2. GPT-5;\n3. o3.",
        "`0.2 <= LR_reported <= 5.0`",
        "`1e-3`",
        "`KI-001`",
        "`PENDING_HUMAN_REVIEW`",
    )
    for fragment in required_fragments:
        require(fragment in text, f"ANALYSIS_SPEC.md is missing required contract text: {fragment}")

    decisions = _register_ids(
        _require_regular_file(repository, "DECISIONS.md"),
        r"`(DEC-[0-9]{3})`",
        "DECISIONS.md",
    )
    exceptions = _register_ids(
        _require_regular_file(repository, "EXCEPTIONS.md"),
        r"`(EXC-[0-9]{3})`",
        "EXCEPTIONS.md",
    )
    issues_path = _require_regular_file(repository, "KNOWN_ISSUES.md")
    issues = _register_ids(issues_path, r"^## (KI-[0-9]{3})", "KNOWN_ISSUES.md")
    issues_text = issues_path.read_text(encoding="utf-8")
    for fragment in ("1.0326838754", "0.9504718609", "0.1454697"):
        require(fragment in issues_text, f"KI-001 is missing frozen evidence-direction value: {fragment}")
    return {
        "decisions": len(decisions),
        "exceptions": len(exceptions),
        "known_issues": len(issues),
    }


def validate_project_rights_pointer(repository: Path = ROOT) -> None:
    project_path = _require_regular_file(repository, "PROJECT.yml")
    try:
        project = yaml.safe_load(project_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise MetadataValidationError(f"Invalid PROJECT.yml: {exc}") from exc
    require(
        project["data"]["rights_registry"] == "metadata/rights_and_licenses.yml",
        "PROJECT.yml must point to metadata/rights_and_licenses.yml",
    )


def validate_metadata_contracts(
    repository: Path = ROOT,
    *,
    schema_root: Path | None = None,
) -> dict[str, Any]:
    """Validate every Stage 2 document and registry in one filesystem root."""

    for relative_path in STAGE2_REQUIRED_PATHS:
        _require_regular_file(repository, relative_path)
    for relative_path in STAGE2_SCHEMA_PATHS:
        _load_schema(repository, relative_path)
    documents = validate_scientific_documents(repository)
    sources = validate_data_sources(repository, schema_root=schema_root)
    dictionary = validate_variable_dictionary(
        sources,
        repository,
        schema_root=schema_root,
    )
    rights = validate_rights_registry(repository, schema_root=schema_root)
    validate_reviewed_source_rights(sources, rights)
    outputs = validate_output_manifest(
        sources,
        repository,
        schema_root=schema_root,
    )
    validate_project_rights_pointer(repository)
    return {
        "scientific_documents": documents,
        "data_sources": len(sources),
        "variable_dictionary": dictionary,
        "rights": rights,
        "output_manifest": outputs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository",
        type=Path,
        default=ROOT,
        help="Repository or materialized candidate root to validate",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary = validate_metadata_contracts(args.repository)
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        yaml.YAMLError,
        jsonschema.ValidationError,
        MetadataValidationError,
    ) as exc:
        print(f"Metadata validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
