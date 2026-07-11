from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def notebook_literals(path: Path, names: set[str]) -> dict[str, Any]:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    found: dict[str, Any] = {}
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        tree = ast.parse("".join(cell["source"]))
        for statement in tree.body:
            if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
                continue
            target = statement.targets[0]
            if isinstance(target, ast.Name) and target.id in names:
                found[target.id] = ast.literal_eval(statement.value)
    missing = names - set(found)
    assert not missing, f"Notebook prompt literals missing: {sorted(missing)}"
    return found


def examples_as_tuples(examples: list[dict[str, Any]]) -> list[tuple[str, str, float]]:
    return [(item["condition"], item["finding"], item["value"]) for item in examples]


def test_fixed_prompt_hashes_and_historical_distinctions() -> None:
    main_path = ROOT / "prompts/main_estimator_v1.json"
    threshold_path = ROOT / "prompts/threshold_perturbation_v1.json"
    assert sha256(main_path) == "63aedb15fbe73a64c91ae5c29fd85c5377c6df71a9fbe005bcd1db4f3c106075"
    assert sha256(threshold_path) == "40c882919c6e31329b23af20b0e2ae81bd62a2b72dcbabb370f1482c41870438"

    main = json.loads(main_path.read_text(encoding="utf-8"))
    threshold = json.loads(threshold_path.read_text(encoding="utf-8"))
    assert len(main["few_shot_sets"]["rich_8"]) == 8
    assert len(main["few_shot_sets"]["minimal_2"]) == 2
    assert main["selection_rule"] == {
        "reasoning_model": "minimal_2",
        "non_reasoning_model": "rich_8",
    }
    assert "noncompressaible" in main_path.read_text(encoding="utf-8")
    assert "noncompressible" in threshold_path.read_text(encoding="utf-8")
    assert main["system_messages"] != threshold["system_messages"]


def test_prompt_json_matches_notebook_literals_exactly() -> None:
    main = json.loads((ROOT / "prompts/main_estimator_v1.json").read_text(encoding="utf-8"))
    main_literals = notebook_literals(
        ROOT / "lr_scraper_estimator.ipynb",
        {"SYSTEM_CORE", "DEFINITION", "BANDS", "FEW_SHOT_RICH", "FEW_SHOT_MIN"},
    )
    assert main["system_messages"] == [
        main_literals["SYSTEM_CORE"].strip(),
        main_literals["DEFINITION"].strip(),
        main_literals["BANDS"].strip(),
    ]
    assert examples_as_tuples(main["few_shot_sets"]["rich_8"]) == main_literals["FEW_SHOT_RICH"]
    assert examples_as_tuples(main["few_shot_sets"]["minimal_2"]) == main_literals["FEW_SHOT_MIN"]

    threshold = json.loads((ROOT / "prompts/threshold_perturbation_v1.json").read_text(encoding="utf-8"))
    threshold_literals = notebook_literals(
        ROOT / "threshold_perturbation_sensitivity_analysis.ipynb",
        {"SYSTEM_CORE", "DEFINITION", "BANDS", "FEW_SHOT_MIN"},
    )
    assert threshold["system_messages"] == [
        threshold_literals["SYSTEM_CORE"].strip(),
        threshold_literals["DEFINITION"].strip(),
        threshold_literals["BANDS"].strip(),
    ]
    assert examples_as_tuples(threshold["few_shot_set"]) == threshold_literals["FEW_SHOT_MIN"]


def test_manuscript_model_scope_and_prompt_mapping() -> None:
    config = json.loads((ROOT / "config/manuscript_models_v1.json").read_text(encoding="utf-8"))
    models = config["manuscript_models"]
    assert [model["api_model"] for model in models] == [
        "gpt-4o-2024-11-20",
        "o3-2025-04-16",
        "gpt-5",
    ]
    assert {model["api_model"]: model["few_shot_set"] for model in models} == {
        "gpt-4o-2024-11-20": "rich_8",
        "o3-2025-04-16": "minimal_2",
        "gpt-5": "minimal_2",
    }
