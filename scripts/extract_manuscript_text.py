#!/usr/bin/env python3
"""Create the format-only author-manuscript text representation.

The source DOCX is read directly as an OOXML package. The extractor preserves
visible paragraph text and document order, marks superscript and subscript
runs, excludes drawing payloads, and refuses to process an unexpected source
file. It does not modify the source document.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ARTICLE_TITLE = "Large language models generate diagnostic likelihood ratios with low mean bias but wide dispersion"
ARTICLE_DOI = "10.1038/s41598-026-61766-2"
SOURCE_DOCX_SHA256 = "98957a4d3f55b26b67b42c2df534a52ce20445730b7c8f48b43933f199c14765"
CANONICAL_VISIBLE_TEXT_SHA256 = "5a88e2f7b5f852cc4c8b814e16b41cb8c7c90f56e22dcaee8102c991d3397451"
EXPECTED_PARAGRAPHS = 193
EXPECTED_SUBSTANTIVE_BLOCKS = 107

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"
BEGIN_MARKER = "----- BEGIN PRE-PRODUCTION AUTHOR MANUSCRIPT -----"
END_MARKER = "----- END PRE-PRODUCTION AUTHOR MANUSCRIPT -----"
FORMAT_TAGS = ("<sup>", "</sup>", "<sub>", "</sub>")


class ExtractionError(RuntimeError):
    """Raised when the source or extracted payload violates the frozen contract."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _run_text(run: ET.Element) -> str:
    pieces: list[str] = []
    for element in run.iter():
        if element.tag == f"{W}t" and element.text:
            pieces.append(element.text)
        elif element.tag == f"{W}tab":
            pieces.append("\t")
        elif element.tag in {f"{W}br", f"{W}cr"}:
            pieces.append("\n")
        elif element.tag == f"{W}noBreakHyphen":
            pieces.append("‑")
        elif element.tag == f"{W}softHyphen":
            pieces.append("\u00ad")
    return normalize_newlines("".join(pieces))


def _render_run(run: ET.Element, *, with_formatting: bool) -> str:
    text = _run_text(run)
    if not text or not with_formatting:
        return text

    vert_align = run.find(f"{W}rPr/{W}vertAlign")
    alignment = vert_align.get(f"{W}val") if vert_align is not None else None
    if alignment == "superscript":
        return f"<sup>{text}</sup>"
    if alignment == "subscript":
        return f"<sub>{text}</sub>"
    return text


def _render_container(element: ET.Element, *, with_formatting: bool) -> str:
    pieces: list[str] = []
    for child in element:
        if child.tag == f"{W}del":
            continue
        if child.tag == f"{W}tab":
            # The frozen inventory treated the paragraph tab stop used by the
            # reference list as a leading visible tab. Preserve that contract.
            pieces.append("\t")
            continue
        if child.tag == f"{W}r":
            pieces.append(_render_run(child, with_formatting=with_formatting))
        else:
            pieces.append(_render_container(child, with_formatting=with_formatting))
    return "".join(pieces)


def extract_blocks(source: Path, *, with_formatting: bool) -> list[str]:
    source_bytes = source.read_bytes()
    actual_source_hash = sha256_bytes(source_bytes)
    if actual_source_hash != SOURCE_DOCX_SHA256:
        raise ExtractionError(f"Unexpected source DOCX hash: expected {SOURCE_DOCX_SHA256}, found {actual_source_hash}")

    try:
        with zipfile.ZipFile(source) as package:
            document_xml = package.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise ExtractionError(f"Invalid DOCX package: {exc}") from exc

    root = ET.fromstring(document_xml)
    body = root.find(f"{W}body")
    if body is None:
        raise ExtractionError("DOCX has no WordprocessingML body")
    if body.find(f"{W}tbl") is not None:
        raise ExtractionError("Unexpected table in source DOCX; extraction would require review")

    paragraphs = body.findall(f"{W}p")
    if len(paragraphs) != EXPECTED_PARAGRAPHS:
        raise ExtractionError(f"Expected {EXPECTED_PARAGRAPHS} paragraphs, found {len(paragraphs)}")
    return [
        normalize_newlines(_render_container(paragraph, with_formatting=with_formatting)) for paragraph in paragraphs
    ]


def canonical_payload(blocks: list[str]) -> str:
    """Join substantive blocks without altering retained block text."""
    substantive = [block for block in blocks if block.strip()]
    if len(substantive) != EXPECTED_SUBSTANTIVE_BLOCKS:
        raise ExtractionError(f"Expected {EXPECTED_SUBSTANTIVE_BLOCKS} substantive blocks, found {len(substantive)}")
    return "\n\n".join(substantive) + "\n"


def strip_formatting_tags(value: str) -> str:
    for tag in FORMAT_TAGS:
        value = value.replace(tag, "")
    return value


def extract_manuscript_payload(representation: str) -> str:
    begin = f"{BEGIN_MARKER}\n"
    end = f"{END_MARKER}\n"
    if representation.count(begin) != 1 or representation.count(end) != 1:
        raise ExtractionError("Manuscript boundary markers are missing or ambiguous")
    return representation.split(begin, 1)[1].split(end, 1)[0]


def render_representation(source: Path) -> str:
    plain_payload = canonical_payload(extract_blocks(source, with_formatting=False))
    actual_visible_hash = sha256_bytes(plain_payload.encode("utf-8"))
    if actual_visible_hash != CANONICAL_VISIBLE_TEXT_SHA256:
        raise ExtractionError(
            f"Visible-text parity check failed: expected {CANONICAL_VISIBLE_TEXT_SHA256}, found {actual_visible_hash}"
        )

    formatted_payload = canonical_payload(extract_blocks(source, with_formatting=True))
    if strip_formatting_tags(formatted_payload) != plain_payload:
        raise ExtractionError("Superscript/subscript markup changed visible manuscript text")

    authors = "Paul Chong; Shuhan He; Kian Samadian; Amal Mohamed; Boyu Peng; Emma Chua; Cory Rohlfsen; Brian W. Locke"
    license_notice = (
        "Copyright © 2026 The Authors. This format-only text representation is shared "
        "under the Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 "
        "International license. License deed: "
        "https://creativecommons.org/licenses/by-nc-nd/4.0/ Legal code: "
        "https://creativecommons.org/licenses/by-nc-nd/4.0/legalcode.en This release "
        "changes format only; under the license, merely changing format does not create "
        "Adapted Material. Sharing requires attribution, must be noncommercial, and must "
        "not distribute adapted material."
    )
    format_notice = (
        "This file preserves the source document's visible paragraph text and order "
        "without copyediting, summarization, or scientific revision. Superscript and "
        "subscript runs are marked with <sup> and <sub> tags. Embedded images, fonts, "
        "layout, and document-package metadata are omitted; the source figure legends "
        "are retained. The publisher Version of Record controls if its wording differs "
        "from this pre-production author manuscript. The frozen repository data and "
        "reference results, rather than this prose representation, control numerical "
        "reproduction."
    )
    header = "\n".join(
        [
            "LLM-readable pre-production author manuscript",
            "",
            f"Article: {ARTICLE_TITLE}",
            f"Authors: {authors}",
            f"Article DOI: https://doi.org/{ARTICLE_DOI}",
            ("Status: Author manuscript immediately before publisher production editing; not the Version of Record."),
            f"Source DOCX SHA-256: {SOURCE_DOCX_SHA256}",
            f"Canonical visible-text SHA-256: {CANONICAL_VISIBLE_TEXT_SHA256}",
            "",
            license_notice,
            "",
            format_notice,
            "",
            BEGIN_MARKER,
            "",
        ]
    )
    return f"{header}{formatted_payload}{END_MARKER}\n"


def numeric_tokens(value: str) -> list[str]:
    return re.findall(r"(?<!\w)[+-]?(?:\d+(?:[.,]\d+)*|\.\d+)(?:[eE][+-]?\d+)?", value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Frozen pre-production author DOCX")
    parser.add_argument("--output", type=Path, help="Output path; omit to write to stdout")
    parser.add_argument(
        "--check-output",
        type=Path,
        help="Compare a committed representation with a fresh extraction",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        rendered = render_representation(args.source)
        if args.check_output is not None:
            current = args.check_output.read_text(encoding="utf-8")
            if current != rendered:
                raise ExtractionError(f"{args.check_output} does not match the source DOCX")
        elif args.output is not None:
            args.output.write_text(rendered, encoding="utf-8", newline="\n")
        else:
            sys.stdout.write(rendered)
    except (ExtractionError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
