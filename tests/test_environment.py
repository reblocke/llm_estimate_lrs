from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_project_version_and_python_contract() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == "1.1.0"
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
    assert (
        "uv run --project tools/cff --frozen --offline --no-sync "
        "cffconvert --validate"
    ) in makefile
    assert "uvx" not in makefile


def test_setup_is_the_only_environment_sync_boundary() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert makefile.count("uv sync") == 2
    assert "\nsetup:\n\tuv sync --frozen\n\tuv sync --project tools/cff --frozen\n" in makefile
    assert "UV_RUN_OFFLINE := uv run --offline --no-sync" in makefile
    assert "uv lock --check --offline" in makefile


def test_missing_validation_environments_fail_with_setup_instruction(tmp_path: Path) -> None:
    missing_root = tmp_path / "missing-root-python"
    root_check = subprocess.run(
        ["make", "environment-check", f"ROOT_PYTHON={missing_root}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert root_check.returncode != 0
    assert "run make setup" in root_check.stdout

    missing_cff = tmp_path / "missing-cffconvert"
    cff_check = subprocess.run(
        ["make", "cff-env-check", f"CFF_CONVERT={missing_cff}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert cff_check.returncode != 0
    assert "run make setup" in cff_check.stdout
