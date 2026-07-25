"""Fail-closed helpers for offline Git object access."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def no_lazy_fetch_environment() -> dict[str, str]:
    """Return an environment for exact, offline Git-object reads."""

    environment = os.environ.copy()
    environment["GIT_NO_LAZY_FETCH"] = "1"
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return environment


def require_full_local_clone(repository: Path) -> None:
    """Reject partial clones and repositories with promisor remotes."""

    environment = no_lazy_fetch_environment()
    partial_clone = subprocess.run(
        ["git", "config", "--local", "--get", "extensions.partialClone"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if partial_clone.returncode == 0 and partial_clone.stdout.strip():
        raise ValueError("Release validation requires a full clone; partial clones are not supported")
    if partial_clone.returncode not in {0, 1}:
        raise ValueError(f"Could not inspect partial-clone configuration: {partial_clone.stderr.strip()}")

    promisor = subprocess.run(
        [
            "git",
            "config",
            "--local",
            "--bool",
            "--get-regexp",
            r"^remote\..*\.promisor$",
        ],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if promisor.returncode == 0 and any(
        line.rsplit(maxsplit=1)[-1] == "true"
        for line in promisor.stdout.splitlines()
        if line.strip()
    ):
        raise ValueError("Release validation requires a full clone; promisor remotes are not supported")
    if promisor.returncode not in {0, 1}:
        raise ValueError(f"Could not inspect promisor configuration: {promisor.stderr.strip()}")


def require_complete_local_objects(repository: Path, revision: str) -> None:
    """Reject partial clones and revisions with objects missing locally."""

    require_full_local_clone(repository)
    environment = no_lazy_fetch_environment()
    closure = subprocess.run(
        ["git", "rev-list", "--objects", "--missing=print", revision],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if closure.returncode != 0:
        raise ValueError(f"Could not inspect local candidate objects: {closure.stderr.strip()}")
    missing = sorted(line[1:] for line in closure.stdout.splitlines() if line.startswith("?"))
    if missing:
        raise ValueError(f"Release candidate has Git objects missing locally: {missing}")
