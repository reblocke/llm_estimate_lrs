#!/usr/bin/env python3
"""Validate repository governance and release contracts without network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import jsonschema
import yaml

if __package__:
    from scripts.git_safety import no_lazy_fetch_environment, require_complete_local_objects
else:
    from git_safety import no_lazy_fetch_environment, require_complete_local_objects

ROOT = Path(__file__).resolve().parents[1]
RELEASE_SCHEMA = ROOT / "release/schemas/release-contract.schema.json"
PROJECT_SCHEMA = ROOT / "schemas/project.schema.json"
ValidationContext = Literal["historical", "prepare", "final"]
VALIDATION_CONTEXTS = {"historical", "prepare", "final"}

REQUIRED_AGENT_HEADINGS = (
    "# Repository instructions",
    "## Purpose",
    "## Setup and checks",
    "## Protected artifacts",
    "## Reproduction and replication boundaries",
    "## Non-negotiable rules",
    "## Version classification",
    "## Handoff evidence",
    "## Definition of done",
)

REQUIRED_AGENT_COMMANDS = (
    "uv lock --check",
    "make setup",
    "make smoke",
    "make audit",
    "make validate-contracts",
    "make test",
    "make reproduce",
)


class ContractValidationError(RuntimeError):
    """Raised when a project or release contract invariant does not hold."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractValidationError(message)


def _git(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        env=no_lazy_fetch_environment(),
    )


def _git_bytes(repository: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=False,
        capture_output=True,
        env=no_lazy_fetch_environment(),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> Any:
    require(path.is_file() and not path.is_symlink(), f"Missing regular {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractValidationError(f"Invalid JSON in {label} {path}: {exc}") from exc


def _validate_schema(instance: Any, schema: Any, label: str) -> None:
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(
            schema,
            format_checker=jsonschema.FormatChecker(),
        )
        validator.validate(instance)
    except jsonschema.SchemaError as exc:
        raise ContractValidationError(f"Invalid JSON schema for {label}: {exc.message}") from exc
    except jsonschema.ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "<root>"
        raise ContractValidationError(f"{label} schema violation at {location}: {exc.message}") from exc


def _validate_safe_relative_path(value: str, label: str) -> None:
    require(isinstance(value, str) and bool(value), f"{label} must be a non-empty string")
    require("\x00" not in value and "\n" not in value and "\r" not in value, f"Unsafe path in {label}: {value!r}")
    require("\\" not in value, f"Backslashes are not allowed in {label}: {value}")
    path = PurePosixPath(value)
    require(not path.is_absolute(), f"Absolute path is not allowed in {label}: {value}")
    require(str(path) == value, f"Path must use canonical POSIX spelling in {label}: {value}")
    require(
        all(part not in {"", ".", ".."} for part in path.parts),
        f"Path traversal is not allowed in {label}: {value}",
    )


def _validate_revision(value: str, label: str) -> None:
    require(isinstance(value, str) and bool(value), f"{label} must be a non-empty string")
    require(
        not value.startswith("-")
        and ".." not in value
        and "@{" not in value
        and not any(character.isspace() for character in value),
        f"Unsafe Git revision in {label}: {value!r}",
    )


def _validate_contract_semantics(contract: Mapping[str, Any]) -> None:
    release_ref = contract["release_ref"]
    require(release_ref == f"v{contract['release_version']}", "release_ref must be v followed by release_version")
    _validate_revision(release_ref, "release_ref")

    required_paths = contract["required_paths"]
    for path in required_paths:
        _validate_safe_relative_path(path, "required_paths")
    require(len(required_paths) == len(set(required_paths)), "required_paths contains duplicate paths")

    protected_paths: list[str] = []
    allowed_origin_refs = {release_ref, *(binding["ref"] for binding in contract["immutable_prior_tags"])}
    for artifact in contract["protected_artifacts"]:
        path = artifact["path"]
        _validate_safe_relative_path(path, "protected_artifacts")
        _validate_revision(artifact["origin_ref"], f"origin_ref for {path}")
        require(
            artifact["origin_ref"] in allowed_origin_refs,
            f"Protected artifact origin_ref is not the release or an immutable prior tag: {path}",
        )
        protected_paths.append(path)
    require(len(protected_paths) == len(set(protected_paths)), "protected_artifacts contains duplicate paths")

    prior_refs = [binding["ref"] for binding in contract["immutable_prior_tags"]]
    require(len(prior_refs) == len(set(prior_refs)), "immutable_prior_tags contains duplicate refs")
    require(release_ref not in prior_refs, "release_ref cannot also be an immutable prior tag")
    for prior_ref in prior_refs:
        _validate_revision(prior_ref, "immutable prior tag ref")

    policy = contract["history_policy"]
    allowed_ref_policy = policy["allowed_refs"]
    namespace = allowed_ref_policy["namespace"].rstrip("/")
    for reference in allowed_ref_policy["values"]:
        require(
            reference == namespace or reference.startswith(f"{namespace}/"),
            f"Allowed ref is outside its declared namespace: {reference}",
        )
    require(
        policy["default_branch_ref"] in allowed_ref_policy["values"],
        "default_branch_ref must be included in history_policy.allowed_refs.values",
    )
    release_tag_ref = f"refs/tags/{release_ref}"
    require(release_tag_ref in policy["allowed_tags"], "Release tag must be included in history_policy.allowed_tags")


def load_release_contract(
    contract_path: Path | str,
    *,
    schema_path: Path | str | None = None,
) -> dict[str, Any]:
    """Load and strictly validate one release contract."""

    path = Path(contract_path)
    selected_schema = Path(schema_path) if schema_path is not None else RELEASE_SCHEMA
    contract = _load_json(path, "release contract")
    schema = _load_json(selected_schema, "release-contract schema")
    require(isinstance(contract, dict), f"Release contract must contain a JSON object: {path}")
    _validate_schema(contract, schema, f"release contract {path.name}")
    _validate_contract_semantics(contract)
    return contract


def load_contract(path: Path | str, repository: Path = ROOT) -> dict[str, Any]:
    """Compatibility entry point for release tooling that uses repository-relative paths."""

    contract_path = Path(path)
    if not contract_path.is_absolute():
        contract_path = repository / contract_path
    repository_root = repository.resolve()
    contract_path = contract_path.resolve()
    try:
        contract_path.relative_to(repository_root)
    except ValueError as exc:
        raise ContractValidationError(f"Release contract must be inside the repository: {contract_path}") from exc
    return load_release_contract(
        contract_path,
        schema_path=repository / "release/schemas/release-contract.schema.json",
    )


def validate_project_metadata(repository: Path = ROOT) -> dict[str, Any]:
    """Validate PROJECT.yml with the repository's strict project schema."""

    project_path = repository / "PROJECT.yml"
    schema_path = repository / "schemas/project.schema.json"
    require(project_path.is_file() and not project_path.is_symlink(), "Missing regular PROJECT.yml")
    schema = _load_json(schema_path, "project schema")
    try:
        project = yaml.safe_load(project_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ContractValidationError(f"Invalid YAML in PROJECT.yml: {exc}") from exc
    require(isinstance(project, dict), "PROJECT.yml must contain a YAML mapping")
    _validate_schema(project, schema, "PROJECT.yml")
    return project


def _agent_files(repository: Path) -> list[str]:
    """Find every case variant without consulting ignore rules or following symlinks."""

    observed: list[str] = []

    def fail_closed(error: OSError) -> None:
        raise ContractValidationError(f"Could not inspect repository instructions: {error}") from error

    for directory, directory_names, file_names in os.walk(
        repository,
        topdown=True,
        onerror=fail_closed,
        followlinks=False,
    ):
        directory_path = Path(directory)
        for name in (*directory_names, *file_names):
            if name.casefold() == "agents.md":
                observed.append((directory_path / name).relative_to(repository).as_posix())
        directory_names[:] = [name for name in directory_names if name != ".git"]
    return sorted(observed)


_CREDENTIAL_NAME = (
    r"(?:[A-Z][A-Z0-9]*_)*(?:"
    r"ACCESS_TOKEN|CLIENT_SECRET|PRIVATE_KEY|SECRET_KEY|ACCESS_KEY|"
    r"API_KEY|APIKEY|AUTH_TOKEN|PASSWORD|PASSWD|TOKEN|SECRET"
    r")"
)


def _contains_credential_assignment(text: str) -> bool:
    credential_key = rf"""["']?{_CREDENTIAL_NAME}["']?"""
    assignment = re.compile(
        rf"""(?imx)
        (?:
            ^[ \t]*
            (?:-[ \t]+)?
            (?:
                (?:export[ \t]+|set[ \t]+)?
                {credential_key}
                [ \t]*(?:=|:)
              |
                \$env:[ \t]*{_CREDENTIAL_NAME}[ \t]*=
            )
          |
            [{{,][ \t]*{credential_key}[ \t]*:
        )
        """
    )
    return assignment.search(text) is not None


def _contains_machine_local_path(text: str) -> bool:
    without_remote_urls = re.sub(
        r"(?i)\b(?:https?|ssh)://[^\s`'\"<>]+",
        "",
        text,
    )
    path_patterns = (
        re.compile(r"(?i)\bfile://"),
        re.compile(r"(?<![A-Za-z0-9_])~(?:[A-Za-z0-9._-]+)?[/\\]"),
        re.compile(r"(?i)(?<![A-Za-z0-9_])[A-Z]:[/\\]"),
        re.compile(r"(?<![A-Za-z0-9_:])(?:\\\\|//)[^/\\\s`'\"<>]+[/\\][^/\\\s`'\"<>]+"),
        re.compile(r"(?m)(?<![A-Za-z0-9_/])/(?=$|[\s`'\"<>)\]}.,;])"),
        re.compile(r"(?<![A-Za-z0-9_/])/(?!/)(?:[^/\s`'\"<>]+(?:/[^/\s`'\"<>]+)*)"),
    )
    return any(pattern.search(without_remote_urls) for pattern in path_patterns)


def validate_agents_policy(repository: Path = ROOT) -> dict[str, Any]:
    """Require the reviewed root policy and reject unsafe embedded payloads."""

    agents_path = repository / "AGENTS.md"
    require(agents_path.is_file() and not agents_path.is_symlink(), "Missing regular root AGENTS.md")
    observed_agents = _agent_files(repository)
    require(observed_agents == ["AGENTS.md"], f"Only the root AGENTS.md is allowed; found {observed_agents}")
    text = agents_path.read_text(encoding="utf-8")

    for heading in REQUIRED_AGENT_HEADINGS:
        require(text.count(heading) == 1, f"AGENTS.md must contain exactly one {heading!r} heading")
    for command in REQUIRED_AGENT_COMMANDS:
        require(command in text, f"AGENTS.md is missing required command: {command}")

    credential_value = re.compile(
        r"(?i)\b(?:sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{12,}|github_pat_[A-Za-z0-9_]{12,})"
    )
    private_key = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
    require(
        not _contains_credential_assignment(text)
        and not credential_value.search(text)
        and not private_key.search(text),
        "AGENTS.md must not contain credentials, tokens, or credential assignments",
    )

    require(not _contains_machine_local_path(text), "AGENTS.md must not contain absolute or machine-local paths")

    external_embed = re.compile(
        r"(?is)(?:!\[[^\]]*\]\(\s*https?://|<(?:img|iframe|script|video|audio|source)\b[^>]*\bsrc\s*=)"
    )
    require(not external_embed.search(text), "AGENTS.md must not contain external embeds")

    markdown_table = re.compile(
        r"(?m)^\s*\|?.+\|.+\|?\s*$\n\s*\|?\s*:?-{3,}(?:\s*\|\s*:?-{3,})+\s*\|?\s*$"
    )
    require(
        not markdown_table.search(text) and "<table" not in text.casefold(),
        "AGENTS.md must not contain data tables",
    )

    digest = re.compile(r"(?i)\b[0-9a-f]{64}\b")
    digest_heading = re.compile(r"(?im)^#{1,6}\s+(?:checksums?|digests?|hash(?:es)?)\s*$")
    require(
        not digest.search(text) and not digest_heading.search(text),
        "AGENTS.md must not contain digest blocks or embedded digests",
    )

    scientific_assignment = re.compile(
        r"(?im)^\s*(?:"
        r"alpha|beta|cutoff|threshold|sample_size|row_count|condition_count|expected_(?:rows|conditions|results?)|"
        r"(?:mean|median|lower|upper)_(?:bias|limit|estimate)|model_(?:id|value)"
        r")\s*[:=]\s*[-+0-9.'\"\[]"
    )
    require(
        not scientific_assignment.search(text),
        "AGENTS.md must not contain embedded scientific-value assignments",
    )

    return {
        "path": "AGENTS.md",
        "required_headings": len(REQUIRED_AGENT_HEADINGS),
        "required_commands": len(REQUIRED_AGENT_COMMANDS),
    }


def _resolve_commit(repository: Path, revision: str, label: str) -> str:
    _validate_revision(revision, label)
    result = _git(repository, "rev-parse", "--verify", f"{revision}^{{commit}}")
    require(result.returncode == 0, f"Could not resolve {label} {revision}: {result.stderr.strip()}")
    return result.stdout.strip()


def _resolve_tree(repository: Path, revision: str, label: str) -> str:
    _validate_revision(revision, label)
    result = _git(repository, "rev-parse", "--verify", f"{revision}^{{tree}}")
    require(result.returncode == 0, f"Could not resolve tree for {label} {revision}: {result.stderr.strip()}")
    return result.stdout.strip()


def _tree_entry(repository: Path, revision: str, relative_path: str) -> tuple[str, str, str]:
    _validate_revision(revision, "tree revision")
    _validate_safe_relative_path(relative_path, "Git tree path")
    result = _git_bytes(repository, "ls-tree", "-z", revision, "--", relative_path)
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    require(result.returncode == 0, f"Could not inspect {relative_path} at {revision}: {stderr}")
    entries = [entry for entry in result.stdout.split(b"\0") if entry]
    require(len(entries) == 1, f"Missing or ambiguous path at {revision}: {relative_path}")
    metadata, separator, raw_path = entries[0].partition(b"\t")
    require(bool(separator), f"Unexpected Git tree entry for {relative_path} at {revision}")
    require(
        raw_path.decode("utf-8", errors="strict") == relative_path,
        f"Git tree returned the wrong path for {relative_path} at {revision}",
    )
    fields = metadata.decode("ascii").split()
    require(len(fields) == 3, f"Unexpected Git tree metadata for {relative_path} at {revision}")
    return fields[0], fields[1], fields[2]


def _require_regular_tree_file(repository: Path, revision: str, relative_path: str) -> str:
    mode, object_type, object_id = _tree_entry(repository, revision, relative_path)
    require(
        mode in {"100644", "100755"} and object_type == "blob",
        f"Contract path is not a regular Git file at {revision}: {relative_path} (mode={mode}, type={object_type})",
    )
    return object_id


def _sha256_blob(repository: Path, object_id: str, label: str) -> str:
    result = _git_bytes(repository, "cat-file", "blob", object_id)
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    require(result.returncode == 0, f"Could not read Git blob for {label}: {stderr}")
    return hashlib.sha256(result.stdout).hexdigest()


def _validate_tag_binding(repository: Path, ref: str, expected_commit: str, expected_tree: str) -> None:
    tag_ref = f"refs/tags/{ref}"
    observed_commit = _resolve_commit(repository, tag_ref, f"tag {ref}")
    require(observed_commit == expected_commit, f"Immutable tag moved: {ref}")
    observed_tree = _resolve_tree(repository, expected_commit, f"commit bound to {ref}")
    require(observed_tree == expected_tree, f"Immutable tag tree changed: {ref}")


def _validate_forbidden_ancestors(repository: Path, target_commit: str, forbidden: list[str]) -> None:
    for ancestor_id in forbidden:
        exists = _git(repository, "cat-file", "-e", f"{ancestor_id}^{{commit}}")
        if exists.returncode != 0:
            continue
        ancestor = _git(repository, "merge-base", "--is-ancestor", ancestor_id, target_commit)
        require(ancestor.returncode in {0, 1}, f"Could not evaluate forbidden ancestor {ancestor_id}")
        require(ancestor.returncode == 1, f"Forbidden commit remains an ancestor of {target_commit}: {ancestor_id}")


def validate_history_policy(
    contract: Mapping[str, Any],
    repository: Path = ROOT,
    *,
    context: ValidationContext = "historical",
    candidate_ref: str | None = None,
) -> None:
    """Validate immutable history and the namespace rules for one explicit context."""

    require(context in VALIDATION_CONTEXTS, f"Unknown release validation context: {context}")
    policy = contract["history_policy"]
    release_ref = contract["release_ref"]
    audited_commit = contract["audited_commit"]
    audited_tree = contract["audited_tree"]

    if policy["complete_history_required"]:
        shallow = _git(repository, "rev-parse", "--is-shallow-repository")
        require(shallow.returncode == 0, f"Could not inspect repository depth: {shallow.stderr.strip()}")
        require(shallow.stdout.strip() == "false", "Release contract validation requires complete, non-shallow history")

    observed_audited_commit = _resolve_commit(repository, audited_commit, "audited commit")
    require(observed_audited_commit == audited_commit, "audited_commit does not identify a commit object")
    observed_tree = _resolve_tree(repository, audited_commit, "audited commit")
    require(observed_tree == audited_tree, "Audited release tree does not match the contract")

    release_tag_ref = f"refs/tags/{release_ref}"
    tag_commit: str | None = None
    if context in {"historical", "final"}:
        tag_commit = _resolve_commit(repository, release_tag_ref, f"release tag {release_ref}")
        require(tag_commit == audited_commit, f"{release_ref} does not resolve to audited_commit")

        if policy["annotated_tag_required"]:
            tag_type = _git(repository, "cat-file", "-t", release_tag_ref)
            require(tag_type.returncode == 0, f"Could not inspect release tag: {tag_type.stderr.strip()}")
            require(tag_type.stdout.strip() == "tag", f"{release_ref} must be an annotated tag")
            tag_message = _git(repository, "for-each-ref", "--format=%(contents)", release_tag_ref)
            require(tag_message.returncode == 0, f"Could not inspect tag annotation: {tag_message.stderr.strip()}")
            require(
                tag_message.stdout.strip() == policy["tag_message"],
                f"{release_ref} annotation must exactly match the contract tag_message",
            )
    else:
        present = _git(repository, "show-ref", "--verify", "--quiet", release_tag_ref)
        require(present.returncode in {0, 1}, f"Could not inspect intended release tag: {release_tag_ref}")
        require(present.returncode == 1, f"Intended release tag must be absent during prepare: {release_tag_ref}")

    if policy["single_root_required"]:
        count = _git(repository, "rev-list", "--count", audited_commit)
        require(count.returncode == 0, f"Could not count release history: {count.stderr.strip()}")
        require(count.stdout.strip() == "1", "single_root_required release history must contain exactly one commit")

    if policy["parentless_release_commit_required"]:
        parents = _git(repository, "rev-list", "--parents", "-n", "1", audited_commit)
        require(parents.returncode == 0, f"Could not inspect release parents: {parents.stderr.strip()}")
        require(len(parents.stdout.split()) == 1, "Release commit must be parentless")

    _validate_forbidden_ancestors(repository, audited_commit, policy["forbidden_ancestors"])
    for binding in contract["immutable_prior_tags"]:
        _validate_tag_binding(repository, binding["ref"], binding["commit"], binding["tree"])

    if context == "historical":
        return

    require(candidate_ref is not None, f"{context} validation requires an explicit candidate_ref")
    candidate_commit = _resolve_commit(repository, candidate_ref, "release candidate")
    candidate_tree = _resolve_tree(repository, candidate_ref, "release candidate")
    require(candidate_commit == audited_commit, "Release candidate does not match audited_commit")
    require(candidate_tree == audited_tree, "Release candidate tree does not match audited_tree")
    if policy["candidate_default_branch_tag_parity_required"]:
        default_commit = _resolve_commit(repository, policy["default_branch_ref"], "default branch")
        require(candidate_commit == default_commit, f"Candidate and {policy['default_branch_ref']} must match")
        if context == "final":
            require(
                tag_commit is not None and candidate_commit == tag_commit,
                f"Candidate, {policy['default_branch_ref']}, and {release_ref} must resolve to the same commit",
            )

    _validate_forbidden_ancestors(repository, candidate_commit, policy["forbidden_ancestors"])
    for reference in policy["forbidden_refs"]:
        present = _git(repository, "show-ref", "--verify", "--quiet", reference)
        require(present.returncode in {0, 1}, f"Could not inspect forbidden ref: {reference}")
        require(present.returncode == 1, f"Forbidden release reference remains: {reference}")

    allowed_ref_policy = policy["allowed_refs"]
    namespace = allowed_ref_policy["namespace"]
    observed_refs_result = _git(repository, "for-each-ref", "--format=%(refname)", namespace)
    require(observed_refs_result.returncode == 0, f"Could not inspect ref namespace: {namespace}")
    observed_refs = {line for line in observed_refs_result.stdout.splitlines() if line}
    allowed_refs = set(allowed_ref_policy["values"])
    require(
        observed_refs <= allowed_refs,
        f"Unexpected refs in {namespace}: {sorted(observed_refs - allowed_refs)}",
    )
    if policy["candidate_default_branch_tag_parity_required"]:
        require(
            policy["default_branch_ref"] in observed_refs,
            f"Default branch ref is absent: {policy['default_branch_ref']}",
        )

    symbolic_head = f"{namespace.rstrip('/')}/HEAD"
    if symbolic_head in observed_refs:
        symbolic = _git(repository, "symbolic-ref", "-q", symbolic_head)
        require(symbolic.returncode == 0, f"{symbolic_head} must be a symbolic ref")
        require(
            symbolic.stdout.strip() == policy["default_branch_ref"],
            f"{symbolic_head} does not point to {policy['default_branch_ref']}",
        )

    tag_refs_result = _git(repository, "for-each-ref", "--format=%(refname)", "refs/tags")
    require(tag_refs_result.returncode == 0, "Could not inspect local tags")
    observed_tags = {line for line in tag_refs_result.stdout.splitlines() if line}
    expected_tags = set(policy["allowed_tags"])
    if context == "prepare":
        expected_tags.remove(release_tag_ref)
    require(
        observed_tags == expected_tags,
        f"Local tags do not match history_policy.allowed_tags for {context}: {sorted(observed_tags)}",
    )


def _validate_historical_paths_and_hashes(
    contract: Mapping[str, Any],
    repository: Path,
    *,
    context: ValidationContext,
) -> None:
    audited_commit = contract["audited_commit"]
    for relative_path in contract["required_paths"]:
        _require_regular_tree_file(repository, audited_commit, relative_path)

    for artifact in contract["protected_artifacts"]:
        relative_path = artifact["path"]
        origin_ref = artifact["origin_ref"]
        resolved_origin = (
            audited_commit
            if context == "prepare" and origin_ref == contract["release_ref"]
            else origin_ref
        )
        origin_blob = _require_regular_tree_file(repository, resolved_origin, relative_path)
        observed_hash = _sha256_blob(repository, origin_blob, f"{resolved_origin}:{relative_path}")
        require(observed_hash == artifact["sha256"], f"Protected Git-object hash changed: {relative_path}")

        audited_blob = _require_regular_tree_file(repository, audited_commit, relative_path)
        audited_hash = _sha256_blob(repository, audited_blob, f"{audited_commit}:{relative_path}")
        require(
            audited_hash == artifact["sha256"],
            f"Protected artifact at audited_commit differs from its declared origin: {relative_path}",
        )


def _validate_current_protected_files(contract: Mapping[str, Any], repository: Path) -> None:
    for artifact in contract["protected_artifacts"]:
        relative_path = artifact["path"]
        path = repository
        parts = PurePosixPath(relative_path).parts
        for index, part in enumerate(parts):
            path = path / part
            component = PurePosixPath(*parts[: index + 1]).as_posix()
            try:
                observed_mode = path.lstat().st_mode
            except FileNotFoundError as exc:
                raise ContractValidationError(
                    f"Protected working-tree path component is missing: {component}"
                ) from exc
            require(
                not stat.S_ISLNK(observed_mode),
                f"Protected working-tree path component is a symlink: {component}",
            )
            if index < len(parts) - 1:
                require(
                    stat.S_ISDIR(observed_mode),
                    f"Protected working-tree path component is not a directory: {component}",
                )
            else:
                require(
                    stat.S_ISREG(observed_mode),
                    f"Protected working-tree path is not a regular file: {relative_path}",
                )
        require(
            _sha256_file(path) == artifact["sha256"],
            f"Protected working-tree file differs from its release contract: {relative_path}",
        )


def validate_release_contract(
    contract_path: Path | str,
    repository: Path = ROOT,
    *,
    check_current_files: bool = True,
    context: ValidationContext = "historical",
    candidate_ref: str | None = None,
    current_files_root: Path | None = None,
) -> dict[str, Any]:
    """Validate one release contract against Git history and protected files."""

    contract = load_contract(contract_path, repository)
    if contract["history_policy"]["complete_history_required"]:
        try:
            require_complete_local_objects(repository, contract["audited_commit"])
        except ValueError as exc:
            raise ContractValidationError(str(exc)) from exc
    validate_history_policy(
        contract,
        repository,
        context=context,
        candidate_ref=candidate_ref,
    )
    _validate_historical_paths_and_hashes(contract, repository, context=context)
    if check_current_files:
        _validate_current_protected_files(contract, current_files_root or repository)
    return contract


def validate_all_contracts(
    repository: Path = ROOT,
    *,
    candidate_contract: Path | str | None = None,
) -> dict[str, Any]:
    """Validate governance plus historical contracts, deferring one explicit candidate."""

    project = validate_project_metadata(repository)
    agents = validate_agents_policy(repository)
    contract_paths = sorted((repository / "release/contracts").glob("*.json"))
    require(bool(contract_paths), "No release contracts found")
    selected_path: Path | None = None
    if candidate_contract is not None:
        requested = Path(candidate_contract)
        if not requested.is_absolute():
            requested = repository / requested
        selected_path = requested.resolve()
        observed_contracts = {path.resolve(): path for path in contract_paths}
        require(
            selected_path in observed_contracts,
            f"Candidate contract must name exactly one release/contracts JSON file: {candidate_contract}",
        )

    releases: list[dict[str, Any]] = []
    for contract_path in contract_paths:
        deferred = selected_path is not None and contract_path.resolve() == selected_path
        contract = (
            load_contract(contract_path, repository)
            if deferred
            else validate_release_contract(contract_path, repository)
        )
        require(
            contract_path.stem == contract["release_ref"],
            f"Contract filename must match release_ref: {contract_path.name}",
        )
        release_summary = {
            "release_ref": contract["release_ref"],
            "audited_commit": contract["audited_commit"],
            "protected_artifacts": len(contract["protected_artifacts"]),
        }
        if deferred:
            release_summary["validation_context"] = "candidate_deferred"
        releases.append(release_summary)
    return {
        "project": project["project"]["id"],
        "agents": agents,
        "releases": releases,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=ROOT)
    parser.add_argument(
        "--candidate-contract",
        type=Path,
        help="Validate this contract structurally and defer its prepare/final history checks",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repository = args.repository.resolve()
    try:
        summary = validate_all_contracts(
            repository,
            candidate_contract=args.candidate_contract,
        )
    except (ContractValidationError, OSError, UnicodeError, KeyError, TypeError, ValueError) as exc:
        print(f"Contract validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
