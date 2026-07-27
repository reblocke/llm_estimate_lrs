#!/usr/bin/env python3
"""Reject release-process residue and private artifacts from the public tree."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import stat
import subprocess
import sys
import tokenize
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

BINARY_SUFFIXES = {
    ".docx",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".pptx",
    ".pyc",
    ".tif",
    ".tiff",
    ".ttf",
    ".woff",
    ".woff2",
    ".xlsx",
    ".zip",
}

ALLOWED_BINARY_PATHS = {
    "NNT_LRs_08-26-2025.xlsx",
    "nnt_lrs_with_estimated.xlsx",
}

ALLOWED_PROCESS_PATHS = {
    "data/model_outputs/threshold_perturbation_v1/threshold_perturbation_reviewer_table.csv",
}

FORBIDDEN_PATH_PARTS = {
    ".co" + "dex",
    "paper",
    "past runs",
    "private",
    "private drafts",
    "proofs",
    "reviewer correspondence",
    "temporary outputs",
    "tmp",
}

SCRATCH_WORD = "scr" + "atch"

FORBIDDEN_PATH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private draft", re.compile(r"(?:^|[/_-])private[-_ ]?drafts?(?:[/_. -]|$)", re.IGNORECASE)),
    (
        "review correspondence",
        re.compile(
            r"(?:^|[/_-])reviewer[-_ ]?(?:response|letter|comments?|correspondence)(?:[/_. -]|$)", re.IGNORECASE
        ),
    ),
    (
        "temporary output",
        re.compile(r"(?:^|[/_-])(?:temporary|temp)[-_ ]?(?:output|file|artifact)s?(?:[/_. -]|$)", re.IGNORECASE),
    ),
    ("stale manuscript", re.compile(r"(?:^|[/_-])old[-_ ]?(?:manuscript|draft)(?:[/_. -]|$)", re.IGNORECASE)),
    (
        "informal working notes",
        re.compile(rf"(?:^|[/_-]){SCRATCH_WORD}[-_ ]?(?:notes?|work)(?:[/_. -]|$)", re.IGNORECASE),
    ),
)

ASSISTANT_PRODUCT_NAMES = ("Co" + "dex", "Chat" + "GPT", "Clau" + "de", "Copi" + "lot")
ASSISTANT_PRODUCT_PATTERN = "|".join(re.escape(name) for name in ASSISTANT_PRODUCT_NAMES)
AI_IDENTITY_PATTERN = rf"(?:AI|LLM|bot|OpenAI|GPT(?:-[A-Za-z0-9.]+)?|{ASSISTANT_PRODUCT_PATTERN})"
PROCESS_SUBJECT_PATTERN = r"(?:repository|documentation|release|code|text|manuscript|README|notebook|workflow)"
AI_CREDIT_PATTERN = (
    rf"(?:(?:by|using|with)\s+(?:an?\s+)?{AI_IDENTITY_PATTERN}(?:\s+(?:assistance|system))?"
    rf"|with\s+(?:the\s+help|assistance)\s+(?:of|from)\s+{AI_IDENTITY_PATTERN})"
)

CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("OpenAI credential pattern", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("GitHub credential pattern", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
)

PROSE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("assistant product name", re.compile(rf"\b(?:{ASSISTANT_PRODUCT_PATTERN})\b", re.IGNORECASE)),
    (
        "AI authorship claim",
        re.compile(
            rf"(?:^\s*(?:authored|prepared|produced|generated|written)\s+{AI_CREDIT_PATTERN}"
            r"|(?:AI|LLM|bot)[- ](?:authored|prepared|written)|"
            rf"{AI_IDENTITY_PATTERN}[- ](?:authored|prepared|written|generated)\s+{PROCESS_SUBJECT_PATTERN}|"
            rf"\b{PROCESS_SUBJECT_PATTERN}\s+(?:was\s+)?"
            r"(?:authored|created|prepared|produced|generated|written)\s+"
            rf"{AI_CREDIT_PATTERN}|{AI_IDENTITY_PATTERN}\s+(?:assisted|helped)\s+"
            rf"(?:(?:with\s+)?(?:preparing|writing|creating|generating)|(?:to\s+)?(?:prepare|write|create|generate))"
            rf"\s+(?:this\s+)?{PROCESS_SUBJECT_PATTERN})\b",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "bot authorship trailer",
        re.compile(rf"(?im)^\s*Co-authored-by:.*(?:bot|OpenAI|{ASSISTANT_PRODUCT_PATTERN}).*$"),
    ),
    ("generated-by trailer", re.compile(r"(?im)^\s*Generated-by:.*$")),
    ("response scaffolding", re.compile(r"\bresponse[- ]ready\b|\bfor the reviewer\b|\brebuttal\b", re.IGNORECASE)),
    ("review lifecycle path", re.compile(r"\breviewer1_followup\b", re.IGNORECASE)),
    ("temporary analysis label", re.compile(r"\badditional requested analyses\b", re.IGNORECASE)),
    (
        "repository-generation scaffold",
        re.compile(rf"\bREADMEBuilder\b|\bimplementation ticket\b|\b{SCRATCH_WORD}(?:pad)?\b", re.IGNORECASE),
    ),
    ("external archive service", re.compile("Zeno" + "do", re.IGNORECASE)),
    (
        "unresolved release marker",
        re.compile(
            r"\b" + "TO" + "DO" + r"\b|\b" + "T" + "BD" + r"\b|TO_BE_" + "FILLED|\bPLACE" + "HOLDER\b",
            re.IGNORECASE,
        ),
    ),
)

TEXT_PATTERNS = (*CREDENTIAL_PATTERNS, *PROSE_PATTERNS)
CREDENTIAL_REASONS = {"OpenAI credential pattern", "GitHub credential pattern"}
ASSET_CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})  ([^\r\n]+)$")
RELEASE_TAG_PATTERN = re.compile(r"^v(?P<version>[0-9]+\.[0-9]+\.[0-9]+)$")


@dataclass(frozen=True)
class Finding:
    path: str
    reason: str
    line: int | None = None

    def render(self) -> str:
        location = self.path if self.line is None else f"{self.path}:{self.line}"
        return f"{location}: {self.reason}"


def _git(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )


def repository_files(repository: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    return [repository / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def _path_findings(relative_path: str) -> list[Finding]:
    lowered = relative_path.lower()
    pure = PurePosixPath(relative_path)
    findings: list[Finding] = []

    if pure.name.lower() == "agents.md" and relative_path != "AGENTS.md":
        findings.append(Finding(relative_path, "only the reviewed root AGENTS.md is allowed"))

    if relative_path not in ALLOWED_PROCESS_PATHS:
        for reason, pattern in FORBIDDEN_PATH_PATTERNS:
            if pattern.search(relative_path):
                findings.append(Finding(relative_path, f"forbidden private/process path: {reason}"))

    if relative_path not in ALLOWED_PROCESS_PATHS:
        for part in pure.parts:
            if part.lower() in FORBIDDEN_PATH_PARTS:
                findings.append(Finding(relative_path, f"forbidden private/process path segment: {part}"))

    if pure.suffix.lower() in BINARY_SUFFIXES and relative_path not in ALLOWED_BINARY_PATHS:
        findings.append(Finding(relative_path, f"unapproved binary artifact ({pure.suffix.lower()})"))

    if "proof" in lowered and relative_path not in ALLOWED_PROCESS_PATHS:
        findings.append(Finding(relative_path, "proof artifact is not allowed in the public release"))
    return findings


def _notebook_text(raw_text: str, path: str) -> str:
    try:
        notebook = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid notebook JSON in {path}: {exc}") from exc

    pieces: list[str] = []
    for cell in notebook.get("cells", []):
        source = "".join(cell.get("source", []))
        if cell.get("cell_type") == "markdown":
            pieces.append(source)
        elif cell.get("cell_type") == "code":
            try:
                comments = [
                    token.string
                    for token in tokenize.generate_tokens(io.StringIO(source).readline)
                    if token.type == tokenize.COMMENT
                ]
            except (IndentationError, tokenize.TokenError):
                comments = [line.partition("#")[2] for line in source.splitlines() if "#" in line]
            pieces.extend(comments)
    return "\n".join(pieces)


def _findings_for_patterns(
    path: str,
    text: str,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
) -> list[Finding]:
    findings: list[Finding] = []
    for reason, pattern in patterns:
        for match in pattern.finditer(text):
            line_number = text.count("\n", 0, match.start()) + 1
            findings.append(Finding(path, reason, line_number))
    return findings


def _text_findings(path: str, text: str) -> list[Finding]:
    return _findings_for_patterns(path, text, TEXT_PATTERNS)


def _credential_findings(path: str, text: str) -> list[Finding]:
    """Scan complete source/metadata where prose-only patterns would be noisy."""
    return [finding for finding in _text_findings(path, text) if finding.reason in CREDENTIAL_REASONS]


def _prose_findings(path: str, text: str) -> list[Finding]:
    return _findings_for_patterns(path, text, PROSE_PATTERNS)


def scan_repository(repository: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in repository_files(repository):
        relative_path = path.relative_to(repository).as_posix()
        findings.extend(_path_findings(relative_path))
        if path.is_symlink():
            findings.append(Finding(relative_path, "tracked or untracked symbolic link is not allowed"))
            continue
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            findings.append(Finding(relative_path, "tracked file is missing from the working tree"))
            continue
        if not stat.S_ISREG(mode):
            findings.append(Finding(relative_path, "nonregular release artifact is not allowed"))
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        try:
            raw_text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(Finding(relative_path, "unrecognized non-text artifact"))
            continue
        if path.suffix.lower() == ".ipynb":
            findings.extend(_credential_findings(relative_path, raw_text))
            findings.extend(_prose_findings(relative_path, _notebook_text(raw_text, relative_path)))
        else:
            findings.extend(_text_findings(relative_path, raw_text))
    return findings


def _is_zero_sha(value: str) -> bool:
    return bool(value) and set(value) == {"0"}


def scan_commit_messages(
    repository: Path,
    *,
    base_commit: str | None = None,
    head_commit: str | None = None,
) -> list[Finding]:
    head = head_commit or "HEAD"
    head_check = _git(repository, "rev-parse", "--verify", f"{head}^{{commit}}")
    if head_check.returncode != 0:
        return [Finding("git-history", f"could not resolve head commit {head!r}: {head_check.stderr.strip()}")]

    if base_commit and not _is_zero_sha(base_commit):
        base_check = _git(repository, "rev-parse", "--verify", f"{base_commit}^{{commit}}")
        if base_check.returncode != 0:
            parents = _git(repository, "rev-list", "--parents", "-n", "1", head)
            if parents.returncode == 0 and len(parents.stdout.split()) == 1:
                revision = f"{head}^!"
            else:
                return [
                    Finding(
                        "git-history",
                        f"could not resolve base commit {base_commit!r}: {base_check.stderr.strip()}",
                    )
                ]
        else:
            revision = f"{base_commit}..{head}"
    elif head_commit or _is_zero_sha(base_commit or ""):
        revision = f"{head}^!"
    else:
        base_check = _git(repository, "rev-parse", "--verify", "origin/main^{commit}")
        revision = f"origin/main..{head}" if base_check.returncode == 0 else f"{head}^!"

    count = _git(repository, "rev-list", "--count", revision)
    if count.returncode != 0:
        return [Finding("git-history", f"could not determine commit range {revision!r}: {count.stderr.strip()}")]
    if count.stdout.strip() == "0":
        revision = f"{head}^!"
    result = _git(repository, "log", revision, "--format=%H%x09%B%x1e")
    if result.returncode != 0:
        return [Finding("git-history", f"could not inspect commit messages: {result.stderr.strip()}")]

    findings: list[Finding] = []
    for record in result.stdout.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        commit, _, message = record.partition("\t")
        findings.extend(_text_findings(f"commit:{commit[:12]}", message))
    return findings


def scan_archive(archive_path: Path) -> list[Finding]:
    findings: list[Finding] = []
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            path = member.filename
            findings.extend(_path_findings(path))
            archived_mode = member.external_attr >> 16
            archived_type = stat.S_IFMT(archived_mode)
            if archived_type not in (0, stat.S_IFREG):
                findings.append(Finding(f"archive:{path}", "nonregular archive member is not allowed"))
                continue
            suffix = PurePosixPath(path).suffix.lower()
            if suffix in BINARY_SUFFIXES:
                continue
            try:
                raw_text = archive.read(member).decode("utf-8")
            except UnicodeDecodeError:
                findings.append(Finding(f"archive:{path}", "unrecognized non-text artifact"))
                continue
            if suffix == ".ipynb":
                findings.extend(_credential_findings(f"archive:{path}", raw_text))
                findings.extend(_prose_findings(f"archive:{path}", _notebook_text(raw_text, path)))
            else:
                findings.extend(_text_findings(f"archive:{path}", raw_text))
    return findings


def scan_text_file(path: Path, label: str | None = None) -> list[Finding]:
    """Scan an externally supplied PR, release, or other publication text."""
    display = label or path.name
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [Finding(display, f"could not read publication text: {exc}")]
    return _text_findings(display, text)


def scan_github_event(path: Path) -> list[Finding]:
    """Scan pull-request or release title/body fields from a GitHub event payload."""
    try:
        event = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [Finding("github-event", f"could not read event payload: {exc}")]

    findings: list[Finding] = []
    for object_name, fields in (("pull_request", ("title", "body")), ("release", ("name", "body"))):
        payload = event.get(object_name)
        if not isinstance(payload, dict):
            continue
        for field in fields:
            value = payload.get(field)
            if isinstance(value, str):
                findings.extend(_text_findings(f"github-event:{object_name}.{field}", value))
    return findings


def scan_release_json(
    path: Path,
    repository: Path,
    contract: Mapping[str, Any] | None = None,
) -> list[Finding]:
    """Scan and verify the exact title/body fetched for a draft or published release."""
    try:
        release = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [Finding("release-json", f"could not read release JSON: {exc}")]
    if not isinstance(release, dict):
        return [Finding("release-json", "release JSON must contain an object")]
    if isinstance(release.get("release"), dict) and not {"name", "body"}.intersection(release):
        release = release["release"]

    findings: list[Finding] = []
    if contract is None:
        tag_name = release.get("tag_name")
        match = RELEASE_TAG_PATTERN.fullmatch(tag_name) if isinstance(tag_name, str) else None
        if match is None:
            findings.append(Finding("release-json:tag_name", "release tag is not a versioned vX.Y.Z tag"))
            release_version = None
            expected_name = None
        else:
            release_version = match.group("version")
            tag_ref = f"refs/tags/{tag_name}"
            tag_type = _git(repository, "cat-file", "-t", tag_ref)
            tag_commit = _git(repository, "rev-parse", "--verify", f"{tag_ref}^{{commit}}")
            head_commit = _git(repository, "rev-parse", "--verify", "HEAD^{commit}")
            tag_message = _git(repository, "for-each-ref", "--format=%(contents)", tag_ref)
            if tag_type.returncode != 0 or tag_type.stdout.strip() != "tag":
                findings.append(Finding("release-json:tag_name", "release tag is missing or not annotated"))
            if tag_commit.returncode != 0 or head_commit.returncode != 0:
                findings.append(
                    Finding(
                        "release-json:tag_name",
                        "release tag or checked-out HEAD could not be resolved",
                    )
                )
            elif tag_commit.stdout.strip() != head_commit.stdout.strip():
                findings.append(Finding("release-json:tag_name", "release tag does not match checked-out HEAD"))
            normalized_message = tag_message.stdout.strip() if tag_message.returncode == 0 else ""
            if not normalized_message or "\n" in normalized_message:
                findings.append(
                    Finding(
                        "release-json:tag_name",
                        "annotated release tag must have one non-empty title message",
                    )
                )
                expected_name = None
            else:
                expected_name = f"{tag_name} — {normalized_message}"
    else:
        release_version = str(contract["release_version"])
        release_ref = str(contract["release_ref"])
        tag_message = str(contract["history_policy"]["tag_message"])
        expected_name = f"{release_ref} — {tag_message}"

    expected_body_path = (
        repository / f"RELEASE_NOTES_v{release_version}.md"
        if release_version is not None
        else None
    )
    try:
        if (
            expected_body_path is None
            or expected_body_path.is_symlink()
            or not expected_body_path.is_file()
        ):
            raise OSError("reviewed release-notes file is missing or unsafe")
        expected_body = expected_body_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        findings.append(Finding("release-json", f"could not read reviewed release notes: {exc}"))
        expected_body = None

    name = release.get("name")
    body = release.get("body")
    if expected_name is not None and name != expected_name:
        findings.append(Finding("release-json:name", "release title differs from the reviewed title"))
    if expected_body is not None and body != expected_body:
        findings.append(
            Finding(
                "release-json:body",
                f"release body differs from RELEASE_NOTES_v{release_version}.md",
            )
        )
    if isinstance(name, str):
        findings.extend(_text_findings("release-json:name", name))
    if isinstance(body, str):
        findings.extend(_text_findings("release-json:body", body))
    return findings


def _safe_checksum_path(relative: str) -> bool:
    path = PurePosixPath(relative)
    return (
        bool(relative)
        and bool(path.parts)
        and "\\" not in relative
        and not path.is_absolute()
        and relative != "."
        and path.as_posix() == relative
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _asset_checksum_findings(
    asset_dir: Path,
    expected_paths: set[str] | frozenset[str],
    actual_paths: set[str],
) -> list[Finding]:
    manifest_relative = "SHA256SUMS"
    manifest = asset_dir / manifest_relative
    expected_entries = set(expected_paths) - {manifest_relative}
    if manifest_relative not in actual_paths or manifest.is_symlink() or not manifest.is_file():
        return [Finding(f"asset:{manifest_relative}", "asset checksum manifest is missing or unsafe")]

    findings: list[Finding] = []
    entries: dict[str, str] = {}
    ordered_paths: list[str] = []
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return [Finding(f"asset:{manifest_relative}", f"could not read asset checksum manifest: {exc}")]

    for line_number, line in enumerate(lines, start=1):
        match = ASSET_CHECKSUM_LINE.fullmatch(line)
        if match is None:
            findings.append(
                Finding(
                    f"asset:{manifest_relative}",
                    "invalid asset checksum line",
                    line_number,
                )
            )
            continue
        expected_hash, relative = match.groups()
        if not _safe_checksum_path(relative):
            findings.append(
                Finding(
                    f"asset:{manifest_relative}",
                    "unsafe asset checksum path",
                    line_number,
                )
            )
            continue
        if relative in entries:
            findings.append(
                Finding(
                    f"asset:{manifest_relative}",
                    "duplicate asset checksum entry",
                    line_number,
                )
            )
            continue
        entries[relative] = expected_hash
        ordered_paths.append(relative)

    if ordered_paths != sorted(ordered_paths):
        findings.append(Finding(f"asset:{manifest_relative}", "asset checksum entries are not sorted"))

    missing_entries = sorted(expected_entries - entries.keys())
    unexpected_entries = sorted(entries.keys() - expected_entries)
    if missing_entries:
        findings.append(
            Finding(
                f"asset:{manifest_relative}",
                f"asset checksum manifest is missing entries: {missing_entries}",
            )
        )
    if unexpected_entries:
        findings.append(
            Finding(
                f"asset:{manifest_relative}",
                f"asset checksum manifest has unexpected entries: {unexpected_entries}",
            )
        )

    for relative in sorted(expected_entries & entries.keys() & actual_paths):
        path = asset_dir / relative
        if path.is_symlink() or not path.is_file():
            continue
        try:
            observed_hash = _sha256_file(path)
        except OSError as exc:
            findings.append(Finding(f"asset:{relative}", f"could not hash release asset: {exc}"))
            continue
        if observed_hash != entries[relative]:
            findings.append(Finding(f"asset:{relative}", "release asset checksum mismatch"))
    return findings


def scan_asset_directory(
    asset_dir: Path,
    contract: Mapping[str, Any],
) -> list[Finding]:
    """Verify and scan the exact contract-versioned release-asset inventory."""
    if __package__:
        from scripts.build_release_assets import expected_asset_paths
    else:
        from build_release_assets import expected_asset_paths

    release_version = str(contract["release_version"])
    expected = expected_asset_paths(release_version)
    if not asset_dir.is_dir() or asset_dir.is_symlink():
        return [Finding(f"asset-dir:{asset_dir}", "release asset directory is missing or unsafe")]

    actual: set[str] = set()
    findings: list[Finding] = []
    for path in sorted(asset_dir.rglob("*")):
        relative = path.relative_to(asset_dir).as_posix()
        if path.is_symlink():
            findings.append(Finding(f"asset:{relative}", "release asset is a symbolic link"))
            continue
        if path.is_dir():
            continue
        if not path.is_file():
            findings.append(Finding(f"asset:{relative}", "release asset is not a regular file"))
            continue
        actual.add(relative)

    for relative in sorted(expected - actual):
        findings.append(Finding(f"asset:{relative}", "expected release asset is missing"))
    for relative in sorted(actual - expected):
        findings.append(Finding(f"asset:{relative}", "unexpected release asset"))

    findings.extend(_asset_checksum_findings(asset_dir, expected, actual))

    for relative in sorted(expected & actual):
        path = asset_dir / relative
        if path.suffix.lower() == ".zip":
            try:
                findings.extend(scan_archive(path))
            except (OSError, zipfile.BadZipFile) as exc:
                findings.append(Finding(f"asset:{relative}", f"could not scan release archive: {exc}"))
        else:
            findings.extend(scan_text_file(path, label=f"asset:{relative}"))
    return findings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument(
        "--archive",
        action="append",
        type=Path,
        default=[],
        help="Release archive to scan; may be supplied more than once",
    )
    parser.add_argument(
        "--text-file",
        action="append",
        type=Path,
        default=[],
        help="Additional PR or release text to scan; may be supplied more than once",
    )
    parser.add_argument("--github-event", type=Path, help="GitHub event JSON containing PR or release text")
    parser.add_argument("--release-json", type=Path, help="GitHub release JSON containing exact name and body fields")
    parser.add_argument(
        "--contract",
        type=Path,
        help="Versioned release contract required for asset verification and optional for exact release verification",
    )
    parser.add_argument(
        "--asset-dir",
        type=Path,
        help="Complete release-asset directory to verify against --contract",
    )
    parser.add_argument("--base-commit", help="Base commit for the commit-message range")
    parser.add_argument("--head-commit", help="Head commit for the commit-message range (defaults to HEAD)")
    parser.add_argument("--skip-commit-messages", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repository = args.repository.resolve()
    findings = scan_repository(repository)
    contract: Mapping[str, Any] | None = None
    if args.contract is not None:
        try:
            if __package__:
                from scripts.validate_contracts import load_contract
            else:
                from validate_contracts import load_contract

            contract = load_contract(args.contract, repository)
        except (ImportError, OSError, RuntimeError, UnicodeError, ValueError) as exc:
            findings.append(Finding("release-contract", f"could not load release contract: {exc}"))
    elif args.asset_dir:
        findings.append(
            Finding(
                "release-contract",
                "--contract is required with --asset-dir",
            )
        )
    if not args.skip_commit_messages:
        findings.extend(
            scan_commit_messages(repository, base_commit=args.base_commit, head_commit=args.head_commit)
        )
    for archive in args.archive:
        findings.extend(scan_archive(archive.resolve()))
    for text_file in args.text_file:
        findings.extend(scan_text_file(text_file.resolve(), label=f"publication-text:{text_file.name}"))
    if args.github_event:
        findings.extend(scan_github_event(args.github_event.resolve()))
    if args.release_json:
        findings.extend(scan_release_json(args.release_json.resolve(), repository, contract))
    if args.asset_dir and contract is not None:
        findings.extend(scan_asset_directory(args.asset_dir.resolve(), contract))

    unique = sorted({finding.render() for finding in findings})
    if unique:
        print("Release hygiene check failed:", file=sys.stderr)
        for finding in unique:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("Release hygiene check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
