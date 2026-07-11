from __future__ import annotations

import ast
import hashlib
import logging
import math
import os
import stat
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Optional

import nbformat
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = (
    "data_analysis.ipynb",
    "supplementary_analyses.ipynb",
    "lr_scraper_estimator.ipynb",
    "threshold_perturbation_sensitivity_analysis.ipynb",
)


def _read(name: str) -> nbformat.NotebookNode:
    return nbformat.read(ROOT / name, as_version=4)


def _all_source(notebook: nbformat.NotebookNode) -> str:
    return "\n".join(cell.source for cell in notebook.cells)


def _code_fingerprint(name: str) -> str:
    notebook = _read(name)
    source = "\0".join(cell.source for cell in notebook.cells if cell.cell_type == "code")
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _non_target_code_fingerprint(name: str, excluded: set[int]) -> str:
    notebook = _read(name)
    payload = "\0".join(
        f"{index}:{cell.cell_type}:{cell.source}"
        for index, cell in enumerate(notebook.cells)
        if cell.cell_type == "code" and index not in excluded
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _literal_assignment(source: str, variable: str):
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == variable
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"Missing literal assignment: {variable}")


def _load_cell_function(name: str, cell_index: int, function_name: str, namespace: dict):
    source = _read(name).cells[cell_index].source
    function = next(
        node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    exec(compile(module, f"{name}:{function_name}", "exec"), namespace)
    return namespace[function_name]


def test_notebooks_are_valid_and_output_free() -> None:
    for name in NOTEBOOKS:
        notebook = _read(name)
        nbformat.validate(notebook)
        for cell in notebook.cells:
            if cell.cell_type == "code":
                assert cell.execution_count is None
                assert cell.outputs == []
                compile(cell.source, f"{name}:{cell.get('id', '')}", "exec")


def test_supplementary_notebook_replaces_lifecycle_artifact() -> None:
    assert not (ROOT / "additional_requested_analyses.ipynb").exists()
    notebook = _read("supplementary_analyses.ipynb")
    assert len(notebook.cells) == 23
    source = _all_source(notebook).lower()
    forbidden_fragments = (
        "response" + "-ready",
        "rebut" + "tal",
        "reviewer1" + "_followup",
        "supplementary " + "docx export",
        "manuscript" + "-ready summary outputs",
        "we " + "added",
    )
    assert not any(fragment in source for fragment in forbidden_fragments)
    assert "supplementary_analyses" in source
    assert "additional_requested_analyses" not in source


def test_frozen_analysis_code_fingerprints() -> None:
    expected = {
        "data_analysis.ipynb": ("7bf2443e0b12c78ffa33fe5791d588889c4d9202d57dae3dcf336868a7f2dd52"),
        "supplementary_analyses.ipynb": ("35cdc655ec6c720aeda678563cfca4b2041fe0a259aa0000ade7551a39245c9f"),
    }
    assert {name: _code_fingerprint(name) for name in expected} == expected


def test_non_target_live_notebook_code_fingerprints() -> None:
    expected = {
        "lr_scraper_estimator.ipynb": (
            {8},
            "54a72538b2cf34fc36efc79695eb543578328f74eb70c57b24b81b0d223ec8cf",
        ),
        "threshold_perturbation_sensitivity_analysis.ipynb": (
            {2, 6, 8},
            "10111fbd68c44c69ec15b3484618deae0e7d88eed0f4f09e6302c6e915301396",
        ),
    }
    assert {
        name: _non_target_code_fingerprint(name, excluded)
        for name, (excluded, _fingerprint) in expected.items()
    } == {name: fingerprint for name, (_excluded, fingerprint) in expected.items()}


def test_analysis_notebook_uses_neutral_headings() -> None:
    source = _all_source(_read("data_analysis.ipynb"))
    assert "### Calibration figures" in source
    assert "Experimental figures" not in source
    assert "Unfortuantely" not in source
    assert "some data this might be" not in source


def test_scraper_defaults_to_exact_manuscript_models() -> None:
    source = _read("lr_scraper_estimator.ipynb").cells[8].source
    assert _literal_assignment(source, "MANUSCRIPT_MODELS") == [
        "gpt-4o-2024-11-20",
        "o3-2025-04-16",
        "gpt-5",
    ]
    assert "SUPPORTED_MODELS = tuple(MODEL_CAPABILITIES)" in source
    assert "MODELS = MANUSCRIPT_MODELS.copy()" in source
    assert "RUN_OPENAI_BATCH" not in source
    assert 'REPLICATION_CONFIRMATION != "YES"' in source
    assert "os.path.lexists(run_dir)" in source
    assert "OpenAI(api_key=api_key, max_retries=0)" in source
    assert "LLM_LR_INPUT_FILE" in source
    assert "before_attempt=checkpoint_attempt" in source
    assert 'audit_row["final_status"] = "in_progress"' in source
    assert '"started_at_utc": started_at_utc' in source
    assert '"completed_at_utc"' in source
    assert "RELEASE_INPUT_FILE" in source
    assert "remaining_calls = max_calls" in source
    assert "allowed_attempts = min(MAX_RETRIES, remaining_calls)" in source
    assert "remaining_calls -= attempts" in source
    assert "outputs are restricted to the repository runs/ directory" in source
    assert "RUN_ID SHA suffix must match the current Git HEAD" in source
    assert "not LIVE_REPLICATION or not _LIVE_GATES_PASSED" in source
    assert "Live replication requires a clean Git worktree" in source
    assert "_atomic_write_csv(output_rows, output_file)" in source
    assert "_atomic_write_csv(pd.DataFrame(audit_rows), retry_audit_file)" in source
    assert "load_dotenv()" not in _read("lr_scraper_estimator.ipynb").cells[1].source


def test_historical_estimator_prompt_examples_remain_distinct() -> None:
    main_source = _read("lr_scraper_estimator.ipynb").cells[8].source
    threshold_source = _read("threshold_perturbation_sensitivity_analysis.ipynb").cells[4].source
    rich = _literal_assignment(main_source, "FEW_SHOT_RICH")
    minimal = _literal_assignment(main_source, "FEW_SHOT_MIN")
    threshold_minimal = _literal_assignment(threshold_source, "FEW_SHOT_MIN")
    assert len(rich) == 8
    assert len(minimal) == 2
    assert len(threshold_minimal) == 2
    assert "noncompressaible" in rich[0][1]
    assert "noncompressaible" in minimal[0][1]
    assert "noncompressible" in threshold_minimal[0][1]


def test_threshold_defaults_to_frozen_analysis_without_client() -> None:
    notebook = _read("threshold_perturbation_sensitivity_analysis.ipynb")
    setup_source = notebook.cells[2].source
    query_source = notebook.cells[8].source
    assert 'LIVE_REPLICATION = os.getenv("LLM_LR_LIVE_REPLICATION") == "1"' in setup_source
    assert "FROZEN_RAW_PATH" in setup_source
    assert "if LIVE_REPLICATION:" in query_source
    assert "get_live_openai_client()" in query_source
    assert "pd.read_csv(FROZEN_RAW_PATH)" in query_source
    assert "will not fall back to a live query" in query_source
    assert "An explicit client is required" in notebook.cells[4].source
    assert "outputs are restricted to the repository runs/ directory" in setup_source
    assert "RUN_ID SHA suffix must match the current Git HEAD" in setup_source
    assert "Live replication requires a clean Git worktree" in setup_source
    assert ("Response" + "-ready") not in _all_source(notebook)
    assert "OpenAI(api_key=api_key, max_retries=0)" in setup_source
    assert "LLM_LR_INPUT_FILE" in setup_source
    assert "staged_cases_df = pd.read_csv(REPLICATION_INPUT_FILE)" in notebook.cells[6].source
    assert "_atomic_write_csv(pd.DataFrame(audit_rows), query_audit_path)" in query_source
    assert '"error_status": "in_progress"' in query_source
    assert "except BaseException as exc:" in query_source
    assert '"started_at_utc": started_at_utc' in query_source
    assert '"completed_at_utc": completed_at_utc' in query_source


def test_threshold_interrupt_checkpoints_reserved_call_and_partial_output(tmp_path: Path) -> None:
    source = _read("threshold_perturbation_sensitivity_analysis.ipynb").cells[8].source
    cases_df = pd.DataFrame(
        [
            {
                "case_id": f"case_{index:02d}",
                "family": "family",
                "condition": "condition",
                "finding_family": "finding family",
                "variant_order": index + 1,
                "threshold_value": index,
                "threshold_units": "unit",
                "comparator": ">",
                "finding_text": f"finding {index}",
                "expected_direction": "nondecreasing",
                "case_source": "test",
                "source_note": "test",
            }
            for index in range(15)
        ]
    )
    calls = 0

    def estimate_lr(**_kwargs) -> float:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        return 2.0

    namespace = {
        "Path": Path,
        "pd": pd,
        "np": np,
        "os": os,
        "stat": stat,
        "tempfile": tempfile,
        "LIVE_REPLICATION": True,
        "MODELS": ["gpt-5"],
        "OUTPUT_DIR": tmp_path,
        "cases_df": cases_df,
        "get_live_openai_client": lambda: object(),
        "estimate_lr": estimate_lr,
        "display": lambda _value: None,
    }
    with pytest.raises(KeyboardInterrupt):
        exec(compile(source, "threshold-query-cell", "exec"), namespace)

    raw = pd.read_csv(tmp_path / "threshold_perturbation_raw.csv")
    audit = pd.read_csv(tmp_path / "query_audit.csv")
    assert len(raw) == 2
    assert len(audit) == 2
    assert audit["attempts"].sum() == 2
    assert audit["error_status"].tolist() == ["ok", "interrupted"]
    assert raw["error_status"].tolist() == ["ok", "interrupted"]
    assert audit["started_at_utc"].notna().all()
    assert audit["completed_at_utc"].notna().all()


@pytest.mark.parametrize(
    ("name", "cell_index"),
    [
        ("lr_scraper_estimator.ipynb", 8),
        ("threshold_perturbation_sensitivity_analysis.ipynb", 8),
    ],
)
def test_atomic_checkpoint_writer_never_follows_symlinks(
    name: str, cell_index: int, tmp_path: Path
) -> None:
    namespace = {
        "os": os,
        "stat": stat,
        "tempfile": tempfile,
        "Path": Path,
        "pd": pd,
    }
    atomic_write = _load_cell_function(name, cell_index, "_atomic_write_csv", namespace)
    frame = pd.DataFrame([{"row_id": "lr_0001", "value": 2.0}])
    outside = tmp_path / "outside.csv"
    outside.write_text("private\n", encoding="utf-8")
    destination = tmp_path / "checkpoint.csv"
    destination.symlink_to(outside)

    with pytest.raises(RuntimeError, match="symlink or special checkpoint"):
        atomic_write(frame, destination)
    assert destination.is_symlink()
    assert outside.read_text(encoding="utf-8") == "private\n"

    destination.unlink()
    predictable = tmp_path / f".{destination.name}.tmp"
    predictable.symlink_to(outside)
    atomic_write(frame, destination)
    assert pd.read_csv(destination).to_dict("records") == [{"row_id": "lr_0001", "value": 2.0}]
    assert outside.read_text(encoding="utf-8") == "private\n"
    assert predictable.is_symlink()
    assert not [
        path
        for path in tmp_path.iterdir()
        if path.name.startswith(f".{destination.name}.") and path != predictable
    ]


def test_openai_client_factories_disable_sdk_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_openai_class(target: dict):
        class FakeOpenAI:
            def __init__(self, **kwargs):
                target.update(kwargs)

        return FakeOpenAI

    for name, cell_index, live_globals in (
        (
            "lr_scraper_estimator.ipynb",
            8,
            {"LIVE_REPLICATION": True, "_LIVE_GATES_PASSED": True},
        ),
        (
            "threshold_perturbation_sensitivity_analysis.ipynb",
            2,
            {"LIVE_REPLICATION": True, "WORKING_DIR": ROOT},
        ),
    ):
        captured = {}
        namespace = {
            "OpenAI": fake_openai_class(captured),
            "os": os,
            "load_dotenv": lambda *_args, **_kwargs: None,
            **live_globals,
        }
        factory_name = "get_openai_client" if name.startswith("lr_") else "get_live_openai_client"
        factory = _load_cell_function(name, cell_index, factory_name, namespace)
        factory()
        assert captured == {"api_key": "test-key", "max_retries": 0}


def test_explicit_retry_wrapper_reserves_exactly_one_call_per_attempt() -> None:
    api_calls: list[int] = []
    reserved: list[int] = []

    def fake_estimate(*_args, **_kwargs) -> float:
        api_calls.append(len(api_calls) + 1)
        if len(api_calls) < 3:
            raise RuntimeError("retry")
        return 2.0

    namespace = {
        "Callable": Callable,
        "Optional": Optional,
        "OpenAI": object,
        "MAX_RETRIES": 8,
        "estimate_lr": fake_estimate,
        "logging": logging,
        "math": math,
        "random": lambda: 0.5,
        "time": time,
    }
    retry = _load_cell_function(
        "lr_scraper_estimator.ipynb",
        8,
        "estimate_lr_until_positive",
        namespace,
    )
    value, attempts = retry(
        "condition",
        "finding",
        "gpt-5",
        object(),
        max_retries=3,
        base_backoff=0,
        before_attempt=reserved.append,
    )
    assert value == 2.0
    assert attempts == 3
    assert api_calls == [1, 2, 3]
    assert reserved == [1, 2, 3]

    api_calls.clear()
    reserved.clear()

    def always_fail(*_args, **_kwargs) -> float:
        api_calls.append(len(api_calls) + 1)
        raise RuntimeError("retry")

    namespace["estimate_lr"] = always_fail
    retry = _load_cell_function(
        "lr_scraper_estimator.ipynb",
        8,
        "estimate_lr_until_positive",
        namespace,
    )
    with pytest.raises(RuntimeError, match="after 2 attempts"):
        retry(
            "condition",
            "finding",
            "gpt-5",
            object(),
            max_retries=2,
            base_backoff=0,
            before_attempt=reserved.append,
        )
    assert api_calls == [1, 2]
    assert reserved == [1, 2]
