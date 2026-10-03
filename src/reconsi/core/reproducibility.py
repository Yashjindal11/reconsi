"""Information recorded with every run so it can be reproduced."""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import subprocess
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from reconsi.configuration.models import ReconConfig


def config_hash(cfg: ReconConfig) -> str:
    text = json.dumps(cfg.model_dump(mode="json", by_alias=True), sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def new_run_id() -> str:
    return f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"


def git_state(cwd: Path | None = None) -> dict[str, Any]:
    """Commit hash and dirty flag of the enclosing Git repository, if any (never raises)."""
    git = shutil.which("git")
    if git is None:
        return {"git_commit": None, "git_dirty": None}
    try:
        head = subprocess.run(  # noqa: S603 - fixed argument list, no shell
            [git, "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if head.returncode != 0:
            return {"git_commit": None, "git_dirty": None}
        status = subprocess.run(  # noqa: S603 - fixed argument list, no shell
            [git, "status", "--porcelain", "--untracked-files=no"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {"git_commit": None, "git_dirty": None}
    return {"git_commit": head.stdout.strip() or None, "git_dirty": bool(status.stdout.strip())}


def package_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name in ("numpy", "pandas", "scipy", "pydantic", "pyarrow", "duckdb"):
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = None
    return out
