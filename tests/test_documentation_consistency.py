from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import yaml

from scripts.validate_contracts import load_contract, validate_project_metadata
from scripts.validate_release import (
    ReleaseValidationError,
    materialized_candidate,
    validate_documentation,
)

ROOT = Path(__file__).resolve().parents[1]
ARTICLE_TITLE = "Large language models generate diagnostic likelihood ratios with low mean bias but wide dispersion"
ARTICLE_DOI = "10.1038/s41598-026-61766-2"
ARTICLE_URL = f"https://doi.org/{ARTICLE_DOI}"
ARTICLE_PUBLISHED_DATE = "2026-07-11"
REPOSITORY_URL = "https://github.com/reblocke/llm_estimate_lrs"
PAPER_SNAPSHOT_VERSION = "1.0.0"
CURRENT_VERSION = "1.1.0"
CURRENT_RELEASE_DATE = "2026-07-27"
MODEL_IDS = ("gpt-4o-2024-11-20", "o3-2025-04-16", "gpt-5")
REPRODUCTION_COMMANDS = ("make reproduce", "make test")

CURRENT_CORE_DOCS = (
    ROOT / "README.md",
    ROOT / "llms.txt",
    ROOT / "RELEASE_NOTES_v1.1.0.md",
    ROOT / "docs" / "REPRODUCIBILITY.md",
)

PUBLIC_READER_DOCS = (
    *CURRENT_CORE_DOCS,
    ROOT / "CHANGELOG.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "docs" / "DATA_PROVENANCE.md",
    ROOT / "docs" / "ACCEPTED_PAPER_CROSSWALK.md",
    ROOT / "docs" / "REPLICATION.md",
    ROOT / "metadata" / "README.md",
    ROOT / "data" / "README.md",
    ROOT / "prompts" / "README.md",
)


def test_article_metadata_and_reproduction_commands_agree() -> None:
    for path in CURRENT_CORE_DOCS:
        text = path.read_text(encoding="utf-8")
        assert ARTICLE_TITLE.casefold() in text.casefold(), path
        assert ARTICLE_DOI in text, path
        assert "unedited early-access article" in text, path
        for command in REPRODUCTION_COMMANDS:
            assert command in text, (path, command)


def test_setup_commands_preserve_historical_release_records() -> None:
    assert "make setup" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert "make setup" in (ROOT / "docs/REPRODUCIBILITY.md").read_text(encoding="utf-8")
    assert "make setup" in (ROOT / "llms.txt").read_text(encoding="utf-8")
    assert "uv sync --frozen" in (ROOT / "RELEASE_NOTES_v1.0.0.md").read_text(
        encoding="utf-8"
    )


def test_model_identifiers_agree() -> None:
    paths = (ROOT / "README.md", ROOT / "llms.txt", ROOT / "docs" / "REPLICATION.md")
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for model_id in MODEL_IDS:
            assert model_id in text, (path, model_id)


def test_current_version_metadata_is_synchronized() -> None:
    citation = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lockfile = (ROOT / "uv.lock").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert citation["cff-version"] == "1.2.0"
    assert citation["title"] == ARTICLE_TITLE
    assert citation["version"] == CURRENT_VERSION
    assert str(citation["date-released"]) == CURRENT_RELEASE_DATE
    assert citation["license"] == "MIT"
    assert citation["repository-code"] == REPOSITORY_URL
    assert project["project"]["version"] == CURRENT_VERSION
    assert project["project"]["urls"]["Homepage"] == ARTICLE_URL
    assert f'name = "llm-estimate-lrs"\nversion = "{CURRENT_VERSION}"' in lockfile
    assert f"## [{CURRENT_VERSION}] - {CURRENT_RELEASE_DATE}" in changelog
    assert "## [Unreleased]" in changelog


def test_citation_metadata_preserves_the_article_record() -> None:
    citation = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))

    assert citation["preferred-citation"]["title"] == ARTICLE_TITLE
    assert citation["preferred-citation"]["doi"] == ARTICLE_DOI
    assert citation["preferred-citation"]["journal"] == "Scientific Reports"
    assert str(citation["preferred-citation"]["date-published"]) == ARTICLE_PUBLISHED_DATE
    assert [author["family-names"] for author in citation["authors"]] == [
        "Chong",
        "He",
        "Samadian",
        "Mohamed",
        "Peng",
        "Chua",
        "Rohlfsen",
        "Locke",
    ]
    assert "identifiers" not in citation


def test_project_metadata_distinguishes_paper_and_current_releases() -> None:
    project = validate_project_metadata(ROOT)

    assert project["schema_version"] == 2
    assert project["project"]["title"] == ARTICLE_TITLE
    assert project["project"]["status"] == "maintenance-only"
    assert project["release"]["frozen_release"] == f"v{PAPER_SNAPSHOT_VERSION}"
    assert project["release"]["current_release"] == f"v{CURRENT_VERSION}"
    assert project["release"]["maintenance_status"] == "maintenance-only"


def test_readme_has_the_reader_first_shape() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    whitespace_delimited_words = readme.split()
    prose_blocks = [
        block
        for block in re.split(r"\n\s*\n", readme)
        if not block.startswith(("```", "#", "-", "|"))
    ]
    headings = (
        "# " + ARTICLE_TITLE,
        "## Article and releases",
        "## Study at a glance",
        "## Reproduce the paper",
        "## Paper-to-code map",
        "## Repository guide",
        "## Run a new model replication",
        "## Provenance, limitations, and reuse",
        "## Citation",
        "## Contributing and contact",
    )

    assert readme.splitlines()[0] == "# " + ARTICLE_TITLE
    assert 900 <= len(whitespace_delimited_words) <= 1050
    assert readme.count("```") == 2
    assert sum(line.startswith("|---") for line in readme.splitlines()) == 2
    assert all(len(re.findall(r"[.!?](?=\s|$)", block)) <= 3 for block in prose_blocks)
    assert all(
        readme.find(left) < readme.find(right)
        for left, right in zip(headings, headings[1:], strict=False)
    )
    assert "> Code and frozen research artifacts supporting" in readme
    assert "### Selected published results" in readme
    assert "## Expected validation results" not in readme


def test_readme_local_links_resolve() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    targets = re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", readme)
    local_targets = {
        target.split("#", 1)[0]
        for target in targets
        if target and not target.startswith(("http://", "https://", "#"))
    }

    assert local_targets
    for target in local_targets:
        assert (ROOT / target).exists(), target


def test_public_reader_documents_avoid_internal_workflow_language() -> None:
    forbidden = (
        "engineering-integrity gate before handoff",
        "human-certification action",
        "pending_human_",
        "stage 2",
        "ticket 01",
        "before stage 3",
    )

    for path in PUBLIC_READER_DOCS:
        normalized = path.read_text(encoding="utf-8").casefold()
        for phrase in forbidden:
            assert phrase not in normalized, (path, phrase)


def test_historical_release_documentation_still_validates_at_v1_tag() -> None:
    contract = load_contract("release/contracts/v1.0.0.json", ROOT)

    with materialized_candidate(ROOT, "v1.0.0") as candidate:
        validate_documentation("final", contract, candidate.root)

        mismatched = dict(contract)
        mismatched["release_version"] = "9.9.9"
        mismatched["release_ref"] = "v9.9.9"
        with pytest.raises(ReleaseValidationError):
            validate_documentation("final", mismatched, candidate.root)


def test_public_documentation_uses_the_stable_supplementary_notebook_name() -> None:
    paths = list(CURRENT_CORE_DOCS) + list((ROOT / "docs").glob("*.md"))
    old_name = "additional_" + "requested_analyses.ipynb"
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "supplementary_analyses.ipynb" in combined
    assert old_name not in combined


def test_license_boundaries_are_explicit() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    provenance = (ROOT / "docs" / "DATA_PROVENANCE.md").read_text(encoding="utf-8")
    manuscript = (ROOT / "llms-full.txt").read_text(encoding="utf-8")

    assert "MIT License applies to original repository software only" in readme
    assert "not relicensed as MIT data" in provenance
    assert "creativecommons.org/licenses/by-nc-nd/4.0/" in readme
    assert "creativecommons.org/licenses/by-nc-nd/4.0/" in provenance
    assert "creativecommons.org/licenses/by-nc-nd/4.0/" in manuscript
