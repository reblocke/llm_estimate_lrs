from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.extract_manuscript_text import (  # noqa: E402
    ARTICLE_DOI,
    ARTICLE_TITLE,
    CANONICAL_VISIBLE_TEXT_SHA256,
    SOURCE_DOCX_SHA256,
    extract_manuscript_payload,
    numeric_tokens,
    render_representation,
    strip_formatting_tags,
)

REPRESENTATION = ROOT / "llms-full.txt"
REPRESENTATION_SHA256 = "b36e4ebed0ad6ca0aea28b0fa91a7575479cd12d7283a8321842528e176ba502"
NUMERIC_TOKEN_SHA256 = "677f79c65b542560ea3d0136f9e4fb7ad01f6e2d915e2cffe468f95c953dd012"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_committed_representation_has_expected_source_and_visible_text() -> None:
    raw_bytes = REPRESENTATION.read_bytes()
    representation = raw_bytes.decode("utf-8")
    payload = extract_manuscript_payload(representation)
    visible_text = strip_formatting_tags(payload)

    assert hashlib.sha256(raw_bytes).hexdigest() == REPRESENTATION_SHA256
    assert sha256_text(visible_text) == CANONICAL_VISIBLE_TEXT_SHA256
    assert len(visible_text) == 36_647
    assert f"Source DOCX SHA-256: {SOURCE_DOCX_SHA256}" in representation
    assert f"Canonical visible-text SHA-256: {CANONICAL_VISIBLE_TEXT_SHA256}" in representation


def test_superscript_subscript_and_numeric_token_parity() -> None:
    payload = extract_manuscript_payload(REPRESENTATION.read_text(encoding="utf-8"))
    visible_text = strip_formatting_tags(payload)

    assert payload.count("<sup>") == payload.count("</sup>") == 31
    assert payload.count("<sub>") == payload.count("</sub>") == 21
    tokens = numeric_tokens(visible_text)
    assert len(tokens) == 491
    assert sha256_text("\n".join(tokens)) == NUMERIC_TOKEN_SHA256


def test_representation_metadata_and_scope() -> None:
    representation = REPRESENTATION.read_text(encoding="utf-8")

    assert f"Article: {ARTICLE_TITLE}" in representation
    assert f"https://doi.org/{ARTICLE_DOI}" in representation
    assert "not the Version of Record" in representation
    assert "creativecommons.org/licenses/by-nc-nd/4.0/" in representation
    assert "creativecommons.org/licenses/by-nc-nd/4.0/legalcode.en" in representation
    assert "merely changing format does not create Adapted Material" in representation
    assert "must be noncommercial" in representation
    assert "must not distribute adapted material" in representation
    assert "Embedded images, fonts, layout, and document-package metadata are omitted" in representation
    assert "Paul Chong; Shuhan He; Kian Samadian; Amal Mohamed" in representation
    assert "word/media/" not in representation
    assert "data:image/" not in representation
    assert "![" not in representation


def test_source_round_trip_when_author_manuscript_is_available() -> None:
    source_value = os.environ.get("AUTHOR_MANUSCRIPT_DOCX")
    if not source_value:
        pytest.skip("Set AUTHOR_MANUSCRIPT_DOCX to run source-DOCX round-trip verification")

    source = Path(source_value)
    assert render_representation(source) == REPRESENTATION.read_text(encoding="utf-8")
