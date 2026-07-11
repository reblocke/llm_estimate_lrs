from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_project_version_and_python_contract() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == "1.0.0"
    assert project["project"]["requires-python"] == ">=3.11"
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.11"


def test_dev_dependencies_use_dependency_groups() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "dependency-groups" in project
    assert "dev-dependencies" not in project.get("tool", {}).get("uv", {})


def test_cff_validator_uses_a_separately_locked_python_311_environment() -> None:
    tool_root = ROOT / "tools/cff"
    tool = tomllib.loads((tool_root / "pyproject.toml").read_text(encoding="utf-8"))
    assert tool["project"]["requires-python"] == ">=3.11,<3.12"
    assert tool["project"]["dependencies"] == ["cffconvert==2.0.0"]
    assert (tool_root / ".python-version").read_text(encoding="utf-8").strip() == "3.11"
    assert (tool_root / "uv.lock").is_file()

    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "uv run --project tools/cff --frozen cffconvert --validate" in makefile
    assert "uvx" not in makefile
