#!/usr/bin/env python3
"""Reproduce accepted-paper reference results from frozen local inputs only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

if __package__:
    from scripts.compute_reference_results import compute_reference_results
else:
    from compute_reference_results import compute_reference_results

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_RELATIVE_PATH = Path("data/curated/diagnostic_lrs_manuscript_v1.csv")
REFERENCE_RELATIVE_PATH = Path("results/reference")
NUMERIC_ABSOLUTE_TOLERANCE = 1e-9
NUMERIC_RELATIVE_TOLERANCE = 1e-9


class ReproductionError(RuntimeError):
    """Raised when an offline reproduction invariant fails."""


class OfflineNetworkError(ReproductionError):
    """Raised when code attempts to create a socket during reproduction."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@contextmanager
def blocked_sockets() -> Iterator[None]:
    """Temporarily reject socket construction and outbound connections."""

    original_socket = socket.socket
    original_create_connection = socket.create_connection

    def deny_network(*_args: Any, **_kwargs: Any) -> Any:
        raise OfflineNetworkError("Network access is blocked during accepted-paper reproduction.")

    socket.socket = deny_network  # type: ignore[assignment]
    socket.create_connection = deny_network  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket = original_socket  # type: ignore[assignment]
        socket.create_connection = original_create_connection  # type: ignore[assignment]


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _lexical_absolute(path: Path) -> Path:
    """Return an absolute normalized path without resolving symbolic links."""
    return Path(os.path.abspath(path))


def _reject_symlink_components(path: Path) -> None:
    """Reject a symlink in any existing component, including the leaf."""
    path = _lexical_absolute(path)
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        if current.is_symlink():
            raise ReproductionError(f"Reproduction output path contains a symbolic link: {current}")


def _validate_output_path(
    output_dir: Path,
    repository_root: Path,
    *,
    replace_output: bool,
) -> Path:
    unresolved_output = _lexical_absolute(output_dir)
    lexical_repository = _lexical_absolute(repository_root)
    _reject_symlink_components(unresolved_output)
    output_dir = unresolved_output.resolve()
    repository_root = lexical_repository.resolve()
    protected_directories = (
        repository_root / "config",
        repository_root / "data",
        repository_root / "manifests",
        repository_root / "prompts",
        repository_root / "results/reference",
    )
    if output_dir == repository_root or any(
        output_dir == path or _is_relative_to(output_dir, path) for path in protected_directories
    ):
        raise ReproductionError(f"Reproduction output cannot be a frozen release path: {output_dir}")
    dedicated_output = lexical_repository / "results/runs/reproduction"
    if replace_output and unresolved_output != dedicated_output:
        raise ReproductionError(f"--replace-output is restricted to the dedicated repository path {dedicated_output}")
    return output_dir


def _prepare_output(output_dir: Path, replace_output: bool) -> None:
    _reject_symlink_components(output_dir)
    if output_dir.exists():
        if not replace_output:
            raise ReproductionError(
                f"Output directory already exists: {output_dir}. Use --replace-output only for this "
                "dedicated reproduction path."
            )
        if output_dir.is_symlink() or not output_dir.is_dir():
            raise ReproductionError(f"Existing reproduction output is not a replaceable directory: {output_dir}")
        _reject_symlink_components(output_dir)
        shutil.rmtree(output_dir)
    _reject_symlink_components(output_dir)
    output_dir.mkdir(parents=True)


def _reference_files(directory: Path) -> dict[str, Path]:
    if not directory.is_dir():
        raise ReproductionError(f"Reference directory is missing: {directory}")
    return {path.relative_to(directory).as_posix(): path for path in sorted(directory.rglob("*")) if path.is_file()}


def _compare_csv(expected: Path, observed: Path) -> None:
    expected_frame = pd.read_csv(expected)
    observed_frame = pd.read_csv(observed)
    if expected_frame.columns.tolist() != observed_frame.columns.tolist():
        raise ReproductionError(f"CSV columns differ for {expected.name}")
    if expected_frame.shape != observed_frame.shape:
        raise ReproductionError(
            f"CSV shape differs for {expected.name}: expected {expected_frame.shape}, got {observed_frame.shape}"
        )
    for column in expected_frame.columns:
        expected_series = expected_frame[column]
        observed_series = observed_frame[column]
        expected_numeric = pd.to_numeric(expected_series, errors="coerce")
        observed_numeric = pd.to_numeric(observed_series, errors="coerce")
        expected_numeric_mask = expected_series.notna() & expected_numeric.notna()
        observed_numeric_mask = observed_series.notna() & observed_numeric.notna()
        if expected_numeric_mask.equals(expected_series.notna()) and observed_numeric_mask.equals(
            observed_series.notna()
        ):
            if not expected_series.isna().equals(observed_series.isna()):
                raise ReproductionError(f"CSV missingness differs in {expected.name}:{column}")
            if not np.allclose(
                expected_numeric.fillna(0).to_numpy(dtype=float),
                observed_numeric.fillna(0).to_numpy(dtype=float),
                atol=NUMERIC_ABSOLUTE_TOLERANCE,
                rtol=NUMERIC_RELATIVE_TOLERANCE,
            ):
                raise ReproductionError(f"CSV numeric values differ in {expected.name}:{column}")
        else:
            expected_text = expected_series.fillna("<NA>").astype(str)
            observed_text = observed_series.fillna("<NA>").astype(str)
            if not expected_text.equals(observed_text):
                raise ReproductionError(f"CSV text values differ in {expected.name}:{column}")


def _compare_json_value(expected: Any, observed: Any, location: str) -> None:
    if isinstance(expected, bool) or isinstance(observed, bool):
        if expected is not observed:
            raise ReproductionError(f"JSON Boolean differs at {location}")
        return
    if isinstance(expected, int | float) and isinstance(observed, int | float):
        if not np.isclose(
            float(expected),
            float(observed),
            atol=NUMERIC_ABSOLUTE_TOLERANCE,
            rtol=NUMERIC_RELATIVE_TOLERANCE,
        ):
            raise ReproductionError(f"JSON numeric value differs at {location}")
        return
    if isinstance(expected, dict) and isinstance(observed, dict):
        if expected.keys() != observed.keys():
            raise ReproductionError(f"JSON object keys differ at {location}")
        for key in expected:
            _compare_json_value(expected[key], observed[key], f"{location}.{key}")
        return
    if isinstance(expected, list) and isinstance(observed, list):
        if len(expected) != len(observed):
            raise ReproductionError(f"JSON list length differs at {location}")
        for index, (expected_item, observed_item) in enumerate(zip(expected, observed, strict=True)):
            _compare_json_value(expected_item, observed_item, f"{location}[{index}]")
        return
    if expected != observed:
        raise ReproductionError(f"JSON value differs at {location}")


def _compare_json(expected: Path, observed: Path) -> None:
    expected_document = json.loads(expected.read_text(encoding="utf-8"))
    observed_document = json.loads(observed.read_text(encoding="utf-8"))
    _compare_json_value(expected_document, observed_document, expected.name)


def compare_reference_artifacts(expected_dir: Path, observed_dir: Path) -> list[dict[str, Any]]:
    """Compare every generated artifact with the tracked reference set."""
    expected_files = _reference_files(expected_dir)
    observed_files = _reference_files(observed_dir)
    if expected_files.keys() != observed_files.keys():
        missing = sorted(expected_files.keys() - observed_files.keys())
        extra = sorted(observed_files.keys() - expected_files.keys())
        raise ReproductionError(f"Reference artifact set differs; missing={missing}, extra={extra}")

    comparisons = []
    for relative_path in expected_files:
        expected = expected_files[relative_path]
        observed = observed_files[relative_path]
        suffix = expected.suffix.lower()
        if suffix == ".csv":
            _compare_csv(expected, observed)
            comparison_mode = "semantic_csv"
        elif suffix == ".json":
            _compare_json(expected, observed)
            comparison_mode = "semantic_json"
        else:
            if expected.read_bytes() != observed.read_bytes():
                raise ReproductionError(f"Text artifact differs: {relative_path}")
            comparison_mode = "byte_exact"
        comparisons.append(
            {
                "path": relative_path,
                "comparison": comparison_mode,
                "status": "match",
                "expected_sha256": sha256_file(expected),
                "observed_sha256": sha256_file(observed),
            }
        )
    return comparisons


def reproduce_paper(
    output_dir: Path,
    *,
    offline: bool,
    replace_output: bool = False,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Path]:
    """Run the frozen offline reproduction and return generated report paths."""
    if not offline:
        raise ReproductionError("Accepted-paper reproduction requires --offline.")
    lexical_repository = _lexical_absolute(repository_root)
    _reject_symlink_components(lexical_repository)
    repository_root = lexical_repository.resolve()
    canonical = repository_root / CANONICAL_RELATIVE_PATH
    reference = repository_root / REFERENCE_RELATIVE_PATH
    if not canonical.is_file():
        raise ReproductionError(f"Frozen canonical input is missing: {canonical}")
    output_dir = _validate_output_path(
        output_dir,
        lexical_repository,
        replace_output=replace_output,
    )
    _prepare_output(output_dir, replace_output)

    generated_reference = output_dir / "reference"
    with blocked_sockets():
        compute_reference_results(canonical, generated_reference)
        comparisons = compare_reference_artifacts(reference, generated_reference)

    validation_report_path = output_dir / "validation_report.json"
    validation_report = {
        "schema_version": 1,
        "status": "passed",
        "comparison_count": len(comparisons),
        "numeric_absolute_tolerance": NUMERIC_ABSOLUTE_TOLERANCE,
        "numeric_relative_tolerance": NUMERIC_RELATIVE_TOLERANCE,
        "artifacts": comparisons,
    }
    validation_report_path.write_text(
        json.dumps(validation_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    run_summary_path = output_dir / "run_summary.json"
    run_summary = {
        "schema_version": 1,
        "mode": "offline_reproduction",
        "status": "passed",
        "canonical_input": CANONICAL_RELATIVE_PATH.as_posix(),
        "tracked_reference": REFERENCE_RELATIVE_PATH.as_posix(),
        "generated_reference": "reference",
        "validation_report": validation_report_path.name,
        "reference_artifacts_compared": len(comparisons),
        "network_blocked": True,
        "api_key_required": False,
        "notebooks_executed": False,
        "live_requests_made": False,
    }
    run_summary_path.write_text(
        json.dumps(run_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "output_dir": output_dir,
        "generated_reference": generated_reference,
        "validation_report": validation_report_path,
        "run_summary": run_summary_path,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--replace-output", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        paths = reproduce_paper(
            args.output,
            offline=args.offline,
            replace_output=args.replace_output,
        )
    except (OSError, ReproductionError, ValueError) as exc:
        print(f"Offline reproduction failed: {exc}", file=sys.stderr)
        return 1
    print(f"Offline reproduction passed: {paths['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
