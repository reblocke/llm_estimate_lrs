from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.validate_contracts import (
    ContractValidationError,
    load_contract,
    load_release_contract,
    validate_agents_policy,
    validate_all_contracts,
    validate_history_policy,
    validate_project_metadata,
    validate_release_contract,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "release/contracts/v1.0.0.json"
CONTRACT_SCHEMA = ROOT / "release/schemas/release-contract.schema.json"
EXPECTED_V1_PROTECTED_ORIGINS = {
    "NNT_LRs_08-26-2025.xlsx": "v1.0.0",
    "nnt_lrs_with_estimated.xlsx": "v1.0.0",
    "data/curated/diagnostic_lrs_manuscript_v1.csv": "v1.0.0",
    "data/model_outputs/auxiliary_gpt-4.1_outputs_v1.csv": "v1.0.0",
    "data/model_outputs/manuscript_model_outputs_v1.csv": "v1.0.0",
    "data/model_outputs/manuscript_query_run_v1.csv": "v1.0.0",
    "data/model_outputs/threshold_perturbation_v1/README.md": "v1.0.0",
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_cases.csv": "v1.0.0",
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_raw.csv": "v1.0.0",
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_reviewer_table.csv": "v1.0.0",
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_summary.csv": "v1.0.0",
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_summary.md": "v1.0.0",
    "data/provenance/curation_log_v1.csv": "v1.0.0",
    "data/provenance/provenance_gaps_v1.csv": "v1.0.0",
    "data/provenance/source_crosswalk_v1.csv": "v1.0.0",
    "config/analysis_categories_v1.json": "v1.0.0",
    "config/manuscript_models_v1.json": "v1.0.0",
    "prompts/main_estimator_v1.json": "v1.0.0",
    "prompts/threshold_perturbation_v1.json": "v1.0.0",
    "results/reference/README.md": "v1.0.0",
    "results/reference/agreement_metrics.csv": "v1.0.0",
    "results/reference/calibration_metrics.csv": "v1.0.0",
    "results/reference/category_counts.csv": "v1.0.0",
    "results/reference/coverage_intervals.csv": "v1.0.0",
    "results/reference/evidence_direction_tests.csv": "v1.0.0",
    "results/reference/feature_type_counts.csv": "v1.0.0",
    "results/reference/kappa_metrics.csv": "v1.0.0",
    "results/reference/laboratory_discrepancy_flags.json": "v1.0.0",
    "results/reference/main_metrics.json": "v1.0.0",
    "results/reference/pairwise_model_comparisons.csv": "v1.0.0",
    "results/reference/reliability_metrics.csv": "v1.0.0",
    "results/reference/reliability_zone_metrics.csv": "v1.0.0",
    "data_analysis.ipynb": "v1.0.0",
    "supplementary_analyses.ipynb": "v1.0.0",
    "lr_scraper_estimator.ipynb": "v1.0.0",
    "threshold_perturbation_sensitivity_analysis.ipynb": "v1.0.0",
    "llms-full.txt": "v1.0.0",
    "manifests/manifest.schema.json": "v1.0.0",
    "manifests/manuscript_run_v1.json": "v1.0.0",
}


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _clone_v1_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    subprocess.run(
        ["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(repository)],
        check=True,
    )
    current_branch = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=repository,
        capture_output=True,
        text=True,
    )
    if current_branch.returncode == 0:
        subprocess.run(["git", "branch", "-M", "main"], cwd=repository, check=True)
    else:
        subprocess.run(["git", "switch", "-q", "-C", "main"], cwd=repository, check=True)
    contract = repository / "release/contracts/v1.0.0.json"
    schema = repository / "release/schemas/release-contract.schema.json"
    contract.parent.mkdir(parents=True, exist_ok=True)
    schema.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CONTRACT_PATH, contract)
    shutil.copy2(CONTRACT_SCHEMA, schema)
    return repository


def _write_project(repository: Path, project: object) -> None:
    (repository / "schemas").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "schemas/project.schema.json", repository / "schemas/project.schema.json")
    (repository / "PROJECT.yml").write_text(
        yaml.safe_dump(project, sort_keys=False),
        encoding="utf-8",
    )


def _future_prepare_repository(tmp_path: Path) -> tuple[Path, Path, str]:
    repository = _clone_v1_repository(tmp_path)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "release@example.invalid"],
        cwd=repository,
        check=True,
    )
    (repository / "maintenance.txt").write_text("maintenance\n", encoding="utf-8")
    subprocess.run(["git", "add", "maintenance.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "Future maintenance release"], cwd=repository, check=True)
    candidate_commit = _git(repository, "rev-parse", "HEAD")
    candidate_tree = _git(repository, "rev-parse", "HEAD^{tree}")

    contract_path = repository / "release/contracts/v1.1.0.json"
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract.update(
        {
            "contract_schema_version": "1.1.0",
            "release_version": "1.1.0",
            "release_ref": "v1.1.0",
            "release_date": "2026-07-27",
            "audited_commit": candidate_commit,
            "audited_tree": candidate_tree,
        }
    )
    contract["history_policy"].update(
        {
            "tag_message": "Future maintenance release",
            "parentless_release_commit_required": False,
            "single_root_required": False,
            "default_branch_ref": "refs/heads/main",
            "forbidden_refs": [],
            "forbidden_ancestors": [],
            "allowed_refs": {
                "namespace": "refs/heads",
                "values": ["refs/heads/main"],
            },
            "allowed_tags": ["refs/tags/v1.0.0", "refs/tags/v1.1.0"],
        }
    )
    contract["immutable_prior_tags"] = [
        {
            "ref": "v1.0.0",
            "commit": "a6824fc712e6d5c7c58edde495c239629356ae35",
            "tree": "9679d031e4983d15db9f216a9ad7df4232d72b78",
        }
    ]
    for artifact in contract["protected_artifacts"]:
        artifact["origin_ref"] = "v1.1.0"
    _write_json(contract_path, contract)
    return repository, contract_path, candidate_commit


def test_repository_contracts_validate_against_v1_git_objects() -> None:
    summary = validate_all_contracts(ROOT)

    assert summary["project"] == "llm-estimate-lrs"
    assert summary["agents"]["required_headings"] == 9
    assert summary["agents"]["required_commands"] == 8
    assert summary["releases"] == [
        {
            "release_ref": "v1.0.0",
            "audited_commit": "a6824fc712e6d5c7c58edde495c239629356ae35",
            "protected_artifacts": 39,
        }
    ]


def test_v1_protected_inventory_and_origins_are_exact() -> None:
    contract = load_release_contract(CONTRACT_PATH, schema_path=CONTRACT_SCHEMA)

    assert contract["contract_schema_version"] == "1.0.0"
    assert "release_date" not in contract
    observed = {
        artifact["path"]: artifact["origin_ref"]
        for artifact in contract["protected_artifacts"]
    }
    assert observed == EXPECTED_V1_PROTECTED_ORIGINS


def test_prepare_reads_release_origin_artifacts_from_untagged_audited_commit(
    tmp_path: Path,
) -> None:
    repository, contract_path, candidate_commit = _future_prepare_repository(tmp_path)

    validated = validate_release_contract(
        contract_path,
        repository,
        context="prepare",
        candidate_ref=candidate_commit,
    )

    assert validated["audited_commit"] == candidate_commit


def test_candidate_contract_is_deferred_while_other_contracts_remain_historical(
    tmp_path: Path,
) -> None:
    repository, contract_path, candidate_commit = _future_prepare_repository(tmp_path)
    shutil.copy2(ROOT / "AGENTS.md", repository / "AGENTS.md")
    shutil.copy2(ROOT / "PROJECT.yml", repository / "PROJECT.yml")
    (repository / "schemas").mkdir(exist_ok=True)
    shutil.copy2(
        ROOT / "schemas/project.schema.json",
        repository / "schemas/project.schema.json",
    )

    with pytest.raises(ContractValidationError, match="Could not resolve release tag v1.1.0"):
        validate_all_contracts(repository)

    summary = validate_all_contracts(repository, candidate_contract=contract_path)

    assert summary["releases"] == [
        {
            "release_ref": "v1.0.0",
            "audited_commit": "a6824fc712e6d5c7c58edde495c239629356ae35",
            "protected_artifacts": 39,
        },
        {
            "release_ref": "v1.1.0",
            "audited_commit": candidate_commit,
            "protected_artifacts": 39,
            "validation_context": "candidate_deferred",
        },
    ]


def test_candidate_contract_must_be_in_release_contract_inventory(tmp_path: Path) -> None:
    outside = tmp_path / "candidate.json"
    shutil.copy2(CONTRACT_PATH, outside)

    with pytest.raises(ContractValidationError, match="exactly one release/contracts"):
        validate_all_contracts(ROOT, candidate_contract=outside)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda contract: contract.pop("audited_tree"), "required property"),
        (lambda contract: contract.update({"unexpected": True}), "Additional properties"),
        (
            lambda contract: contract["required_paths"].append("../outside"),
            "does not match",
        ),
        (
            lambda contract: contract["protected_artifacts"].append(
                dict(contract["protected_artifacts"][0])
            ),
            "duplicate paths",
        ),
    ],
)
def test_release_contract_rejects_schema_and_path_failures(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    mutation(contract)
    candidate = tmp_path / "contract.json"
    _write_json(candidate, contract)

    with pytest.raises(ContractValidationError, match=message):
        load_release_contract(candidate, schema_path=CONTRACT_SCHEMA)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda contract: contract.pop("release_date"), "release_date"),
        (
            lambda contract: contract.update({"contract_schema_version": "1.0.0"}),
            "schema 1.1.0",
        ),
    ],
)
def test_successor_contract_requires_schema_1_1_and_release_date(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract.update(
        {
            "contract_schema_version": "1.1.0",
            "release_version": "1.1.0",
            "release_ref": "v1.1.0",
            "release_date": "2026-07-27",
            "audited_commit": "b" * 40,
            "audited_tree": "c" * 40,
        }
    )
    contract["history_policy"]["allowed_tags"].append("refs/tags/v1.1.0")
    mutation(contract)
    candidate = tmp_path / "contract.json"
    _write_json(candidate, contract)

    with pytest.raises(ContractValidationError, match=message):
        load_release_contract(candidate, schema_path=CONTRACT_SCHEMA)


def test_release_contract_path_must_stay_inside_repository(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    shutil.copy2(CONTRACT_PATH, outside)

    with pytest.raises(ContractValidationError, match="inside the repository"):
        load_contract(outside, ROOT)


def test_release_contract_rejects_wrong_historical_hash(tmp_path: Path) -> None:
    repository = _clone_v1_repository(tmp_path)
    contract_path = repository / "release/contracts/v1.0.0.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["protected_artifacts"][0]["sha256"] = "0" * 64
    _write_json(contract_path, contract)

    with pytest.raises(ContractValidationError, match="Protected Git-object hash changed"):
        validate_release_contract(contract_path, repository)


@pytest.mark.parametrize("truthy", ["true", "yes", "on", "1"])
def test_historical_contract_rejects_promisor_repository(
    tmp_path: Path,
    truthy: str,
) -> None:
    repository = _clone_v1_repository(tmp_path)
    subprocess.run(
        ["git", "config", "remote.origin.promisor", truthy],
        cwd=repository,
        check=True,
    )

    with pytest.raises(ContractValidationError, match="promisor remotes are not supported"):
        validate_release_contract(
            repository / "release/contracts/v1.0.0.json",
            repository,
        )


@pytest.mark.parametrize("as_symlink", [False, True])
def test_release_contract_rejects_current_protected_file_drift(
    tmp_path: Path,
    as_symlink: bool,
) -> None:
    repository = _clone_v1_repository(tmp_path)
    contract_path = repository / "release/contracts/v1.0.0.json"
    protected = repository / "results/reference/main_metrics.json"
    if as_symlink:
        outside = tmp_path / "outside.json"
        outside.write_text("{}\n", encoding="utf-8")
        protected.unlink()
        protected.symlink_to(outside)
        expected = "is a symlink"
    else:
        protected.write_text("{}\n", encoding="utf-8")
        expected = "differs from its release contract"

    with pytest.raises(ContractValidationError, match=expected):
        validate_release_contract(contract_path, repository)


def test_release_contract_rejects_symlinked_protected_parent_even_when_hashes_match(
    tmp_path: Path,
) -> None:
    repository = _clone_v1_repository(tmp_path)
    contract_path = repository / "release/contracts/v1.0.0.json"
    protected_parent = repository / "results/reference"
    outside_parent = tmp_path / "outside-reference"
    shutil.copytree(protected_parent, outside_parent)
    shutil.rmtree(protected_parent)
    protected_parent.symlink_to(outside_parent, target_is_directory=True)

    with pytest.raises(
        ContractValidationError,
        match=r"path component is a symlink: results/reference",
    ):
        validate_release_contract(contract_path, repository)


def _copy_agent_policy(repository: Path) -> Path:
    policy = repository / "AGENTS.md"
    policy.write_text((ROOT / "AGENTS.md").read_text(encoding="utf-8"), encoding="utf-8")
    return policy


def test_agent_policy_rejects_nested_case_variants(tmp_path: Path) -> None:
    _copy_agent_policy(tmp_path)
    nested = tmp_path / "docs/agents.md"
    nested.parent.mkdir()
    nested.write_text("# Unexpected instructions\n", encoding="utf-8")

    with pytest.raises(ContractValidationError, match="Only the root AGENTS.md is allowed"):
        validate_agents_policy(tmp_path)


def test_agent_policy_rejects_ignored_nested_instructions(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Policy Test"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "policy@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    _copy_agent_policy(tmp_path)
    (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    subprocess.run(["git", "add", "AGENTS.md", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "Add root policy"], cwd=tmp_path, check=True)
    nested = tmp_path / "ignored/AgEnTs.Md"
    nested.parent.mkdir()
    nested.write_text("# Ignored but still unsafe\n", encoding="utf-8")

    with pytest.raises(ContractValidationError, match="Only the root AGENTS.md is allowed"):
        validate_agents_policy(tmp_path)


def test_agent_policy_rejects_nested_instruction_directory(tmp_path: Path) -> None:
    _copy_agent_policy(tmp_path)
    (tmp_path / "docs/AGENTS.md").mkdir(parents=True)

    with pytest.raises(ContractValidationError, match="Only the root AGENTS.md is allowed"):
        validate_agents_policy(tmp_path)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("\nAPI_KEY=example\n", "credentials"),
        ("\nLocal source: /Users/example/project\n", "machine-local paths"),
        ("\n" + "a" * 64 + "\n", "embedded digests"),
        ("\nthreshold = 0.25\n", "scientific-value assignments"),
        ("\n![remote](https://example.invalid/image.png)\n", "external embeds"),
    ],
)
def test_agent_policy_rejects_embedded_payloads(
    tmp_path: Path,
    payload: str,
    message: str,
) -> None:
    policy = _copy_agent_policy(tmp_path)
    policy.write_text(policy.read_text(encoding="utf-8") + payload, encoding="utf-8")

    with pytest.raises(ContractValidationError, match=message):
        validate_agents_policy(tmp_path)


@pytest.mark.parametrize(
    "payload",
    [
        "GITHUB_TOKEN=example",
        "export OPENAI_API_KEY=example",
        "set AWS_ACCESS_TOKEN=example",
        'set "AZURE_CLIENT_SECRET=example"',
        "$env:GITHUB_TOKEN = 'example'",
        "github_token: example",
        "- GITHUB_TOKEN: example",
        "AWS_SECRET_ACCESS_KEY=example",
        "service_password: example",
        "PRIVATE_KEY=",
        '"GITHUB_TOKEN": example',
        "{GITHUB_TOKEN: example}",
        '{"GITHUB_TOKEN": example}',
        "environment: {SAFE_FLAG: true, GITHUB_TOKEN: example}",
    ],
)
def test_agent_policy_rejects_provider_neutral_credential_assignments(
    tmp_path: Path,
    payload: str,
) -> None:
    policy = _copy_agent_policy(tmp_path)
    policy.write_text(
        policy.read_text(encoding="utf-8") + f"\n{payload}\n",
        encoding="utf-8",
    )

    with pytest.raises(ContractValidationError, match="credentials"):
        validate_agents_policy(tmp_path)


def test_agent_policy_allows_credential_prose_without_assignments(tmp_path: Path) -> None:
    policy = _copy_agent_policy(tmp_path)
    policy.write_text(
        policy.read_text(encoding="utf-8")
        + "\nGITHUB_TOKEN must never be stored here.\n"
        + "Document credential handling without values.\n"
        + "TOKEN_ROTATION_POLICY=true\n",
        encoding="utf-8",
    )

    validate_agents_policy(tmp_path)


@pytest.mark.parametrize(
    "payload",
    [
        "Local tool: /opt/release/bin",
        "Local tool:/opt/release/bin",
        "Repository root: /",
        "Mounted source: /Volumes/research/archive",
        "Mounted source:/Volumes/research/archive",
        "Home checkout: ~/projects/release",
        "Named home: ~reviewer/projects/release",
        r"Windows checkout: C:\Users\reviewer\project",
        "Windows checkout: D:/research/project",
        r"Network share: \\server\share\project",
        "Network share: //server/share/project",
        "Local URI: file:///private/tmp/release",
    ],
)
def test_agent_policy_rejects_machine_local_path_syntax(
    tmp_path: Path,
    payload: str,
) -> None:
    policy = _copy_agent_policy(tmp_path)
    policy.write_text(
        policy.read_text(encoding="utf-8") + f"\n{payload}\n",
        encoding="utf-8",
    )

    with pytest.raises(ContractValidationError, match="machine-local paths"):
        validate_agents_policy(tmp_path)


@pytest.mark.parametrize(
    "payload",
    [
        "Documentation: https://example.invalid/project/path",
        "Repository URL: ssh://git@example.invalid/project/repository",
        "IPv6 documentation: https://[2001:db8::1]/project/path",
        "IPv6 repository: ssh://git@[2001:db8::1]/project/repository",
        "Git remote: git@example.invalid:project/repository.git",
        "Default ref: refs/heads/main",
        "Repository file: docs/RELEASE_PROCESS.md",
        "Use and/or when the prose requires it.",
    ],
)
def test_agent_policy_allows_urls_refs_relative_paths_and_prose(
    tmp_path: Path,
    payload: str,
) -> None:
    policy = _copy_agent_policy(tmp_path)
    policy.write_text(
        policy.read_text(encoding="utf-8") + f"\n{payload}\n",
        encoding="utf-8",
    )

    validate_agents_policy(tmp_path)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_project_schema_rejects_missing_and_extra_fields(
    tmp_path: Path,
    mutation: str,
) -> None:
    project = yaml.safe_load((ROOT / "PROJECT.yml").read_text(encoding="utf-8"))
    if mutation == "missing":
        project["roles"].pop("data_steward")
    else:
        project["project"]["unexpected"] = True
    _write_project(tmp_path, project)

    with pytest.raises(ContractValidationError, match="schema violation"):
        validate_project_metadata(tmp_path)


@pytest.mark.parametrize("verdict", ["passed", "failed"])
def test_project_schema_accepts_complete_verification_evidence(
    tmp_path: Path,
    verdict: str,
) -> None:
    project = yaml.safe_load((ROOT / "PROJECT.yml").read_text(encoding="utf-8"))
    project["verification"] = {
        "last_verified_date": "2026-07-24",
        "last_verified_commit": "a6824fc712e6d5c7c58edde495c239629356ae35",
        "reviewer": "Independent Reviewer",
        "verdict": verdict,
    }
    _write_project(tmp_path, project)

    assert validate_project_metadata(tmp_path)["verification"]["verdict"] == verdict


@pytest.mark.parametrize("verdict", ["passed", "failed"])
@pytest.mark.parametrize(
    ("field", "pending_value"),
    [
        ("last_verified_date", "PENDING_INDEPENDENT_RUN"),
        ("last_verified_commit", "PENDING_INDEPENDENT_RUN"),
        ("reviewer", "PENDING_HUMAN_ASSIGNMENT"),
    ],
)
def test_project_schema_rejects_completed_verdict_with_pending_evidence(
    tmp_path: Path,
    verdict: str,
    field: str,
    pending_value: str,
) -> None:
    project = yaml.safe_load((ROOT / "PROJECT.yml").read_text(encoding="utf-8"))
    project["verification"] = {
        "last_verified_date": "2026-07-24",
        "last_verified_commit": "a6824fc712e6d5c7c58edde495c239629356ae35",
        "reviewer": "Independent Reviewer",
        "verdict": verdict,
    }
    project["verification"][field] = pending_value
    _write_project(tmp_path, project)

    with pytest.raises(ContractValidationError, match="schema violation"):
        validate_project_metadata(tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("last_verified_date", "2026-07-24"),
        ("last_verified_commit", "a6824fc712e6d5c7c58edde495c239629356ae35"),
        ("reviewer", "Independent Reviewer"),
    ],
)
def test_project_schema_allows_partial_evidence_while_pending(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    project = yaml.safe_load((ROOT / "PROJECT.yml").read_text(encoding="utf-8"))
    project["verification"][field] = value
    _write_project(tmp_path, project)

    assert validate_project_metadata(tmp_path)["verification"]["verdict"] == "pending"


def test_prior_tag_binding_rejects_moved_tag(tmp_path: Path) -> None:
    repository = tmp_path / "history"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "release@example.invalid"], cwd=repository, check=True)
    (repository / "record.txt").write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "record.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "Initial release"], cwd=repository, check=True)
    prior_commit = _git(repository, "rev-parse", "HEAD")
    prior_tree = _git(repository, "rev-parse", "HEAD^{tree}")
    subprocess.run(["git", "tag", "-a", "v1.0.0", "-m", "Initial release"], cwd=repository, check=True)

    (repository / "record.txt").write_text("v2\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "Future release"], cwd=repository, check=True)
    release_commit = _git(repository, "rev-parse", "HEAD")
    release_tree = _git(repository, "rev-parse", "HEAD^{tree}")
    subprocess.run(["git", "tag", "-a", "v2.0.0", "-m", "Future release"], cwd=repository, check=True)

    contract = {
        "release_ref": "v2.0.0",
        "audited_commit": release_commit,
        "audited_tree": release_tree,
        "history_policy": {
            "complete_history_required": True,
            "annotated_tag_required": True,
            "tag_message": "Future release",
            "parentless_release_commit_required": False,
            "single_root_required": False,
            "candidate_default_branch_tag_parity_required": False,
            "default_branch_ref": "refs/heads/main",
            "forbidden_refs": [],
            "forbidden_ancestors": [],
            "allowed_refs": {"namespace": "refs/heads", "values": ["refs/heads/main"]},
            "allowed_tags": ["refs/tags/v1.0.0", "refs/tags/v2.0.0"],
        },
        "immutable_prior_tags": [
            {"ref": "v1.0.0", "commit": prior_commit, "tree": prior_tree}
        ],
    }
    validate_history_policy(contract, repository)

    subprocess.run(
        ["git", "tag", "-f", "-a", "v1.0.0", "-m", "Moved tag", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    with pytest.raises(ContractValidationError, match="Immutable tag moved"):
        validate_history_policy(contract, repository)
