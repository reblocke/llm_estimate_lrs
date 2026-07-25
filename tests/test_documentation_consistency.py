from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
import yaml

from scripts.validate_contracts import load_contract
from scripts.validate_release import ReleaseValidationError, validate_documentation

ROOT = Path(__file__).resolve().parents[1]
ARTICLE_TITLE = "Large language models generate diagnostic likelihood ratios with low mean bias but wide dispersion"
ARTICLE_DOI = "10.1038/s41598-026-61766-2"
ARTICLE_URL = f"https://doi.org/{ARTICLE_DOI}"
ARTICLE_PUBLISHED_DATE = "2026-07-11"
REPOSITORY_RELEASE_DATE = "2026-07-11"
PUBLICATION_STATUS = (
    "Published online in *Scientific Reports* on 11 July 2026 as a citable, unedited early-access article; "
    "publisher production editing remains ongoing"
)
README_PUBLICATION_STATUS = (
    "Published online in *Scientific Reports* on 11 July 2026 as an early-access article."
)
REPOSITORY_URL = "https://github.com/reblocke/llm_estimate_lrs"
VERSION = "1.0.0"
MODEL_IDS = ("gpt-4o-2024-11-20", "o3-2025-04-16", "gpt-5")
REPRODUCTION_COMMANDS = ("make reproduce", "make test")

CORE_DOCS = (
    ROOT / "README.md",
    ROOT / "llms.txt",
    ROOT / "RELEASE_NOTES_v1.0.0.md",
    ROOT / "docs" / "REPRODUCIBILITY.md",
)


def test_article_metadata_and_reproduction_commands_agree() -> None:
    for path in CORE_DOCS:
        text = path.read_text(encoding="utf-8")
        assert ARTICLE_TITLE.casefold() in text.casefold(), path
        assert ARTICLE_DOI in text, path
        for command in REPRODUCTION_COMMANDS:
            assert command in text, (path, command)


def test_setup_commands_preserve_historical_release_records() -> None:
    assert "make setup" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert "make setup" in (ROOT / "docs/REPRODUCIBILITY.md").read_text(encoding="utf-8")
    assert "uv sync --frozen" in (ROOT / "llms.txt").read_text(encoding="utf-8")
    assert "uv sync --frozen" in (ROOT / "RELEASE_NOTES_v1.0.0.md").read_text(
        encoding="utf-8"
    )


def test_model_identifiers_agree() -> None:
    paths = (ROOT / "README.md", ROOT / "llms.txt", ROOT / "docs" / "REPLICATION.md")
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for model_id in MODEL_IDS:
            assert model_id in text, (path, model_id)


def test_citation_metadata_is_complete_and_article_specific() -> None:
    citation = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))

    assert citation["cff-version"] == "1.2.0"
    assert citation["version"] == VERSION
    assert citation["license"] == "MIT"
    assert citation["repository-code"] == REPOSITORY_URL
    assert citation["preferred-citation"]["title"] == ARTICLE_TITLE
    assert citation["preferred-citation"]["doi"] == ARTICLE_DOI
    assert citation["preferred-citation"]["journal"] == "Scientific Reports"
    assert str(citation["preferred-citation"]["date-published"]) == ARTICLE_PUBLISHED_DATE
    assert str(citation["date-released"]) == REPOSITORY_RELEASE_DATE
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

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if "date-released" in citation:
        assert f"## [1.0.0] - {citation['date-released']}" in changelog
        assert "## [1.0.0] - Unreleased" not in changelog
    else:
        assert "## [1.0.0] - Unreleased" in changelog


def test_article_and_repository_release_statuses_are_final() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    machine_index = (ROOT / "llms.txt").read_text(encoding="utf-8")
    release_notes = (ROOT / "RELEASE_NOTES_v1.0.0.md").read_text(encoding="utf-8")
    reproducibility = (ROOT / "docs/REPRODUCIBILITY.md").read_text(encoding="utf-8")

    assert README_PUBLICATION_STATUS in readme
    assert PUBLICATION_STATUS in release_notes
    assert PUBLICATION_STATUS in reproducibility
    assert PUBLICATION_STATUS.replace("*", "") in machine_index
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["urls"]["Homepage"] == ARTICLE_URL
    citation = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    assert str(citation["date-released"]) == REPOSITORY_RELEASE_DATE
    assert "`v1.0.0` GitHub release" in release_notes
    assert "prepared repository release" not in release_notes
    assert "under revision" not in readme


def test_release_documentation_uses_selected_contract() -> None:
    contract = load_contract("release/contracts/v1.0.0.json", ROOT)
    validate_documentation("final", contract)

    mismatched = dict(contract)
    mismatched["release_version"] = "9.9.9"
    mismatched["release_ref"] = "v9.9.9"
    with pytest.raises(ReleaseValidationError, match="release contract"):
        validate_documentation("final", mismatched)


def test_public_documentation_uses_the_stable_supplementary_notebook_name() -> None:
    paths = list(CORE_DOCS) + list((ROOT / "docs").glob("*.md"))
    old_name = "additional_" + "requested_analyses.ipynb"
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "supplementary_analyses.ipynb" in combined
    assert old_name not in combined


def test_license_boundaries_are_explicit() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    provenance = (ROOT / "docs" / "DATA_PROVENANCE.md").read_text(encoding="utf-8")
    manuscript = (ROOT / "llms-full.txt").read_text(encoding="utf-8")

    assert "MIT License" in readme and "original repository software only" in readme
    assert "not relicensed as MIT data" in provenance
    assert "creativecommons.org/licenses/by-nc-nd/4.0/" in readme
    assert "creativecommons.org/licenses/by-nc-nd/4.0/" in provenance
    assert "creativecommons.org/licenses/by-nc-nd/4.0/" in manuscript
