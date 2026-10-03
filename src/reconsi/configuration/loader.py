"""Load and validate YAML reconciliation jobs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from reconsi.configuration.models import ReconConfig
from reconsi.core.errors import ConfigurationError

MAX_CONFIG_BYTES = 1_000_000


def _format_errors(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)


def config_from_dict(data: Any) -> ReconConfig:
    if not isinstance(data, dict):
        raise ConfigurationError("configuration must be a mapping at the top level")
    try:
        return ReconConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigurationError("invalid configuration:\n" + _format_errors(exc)) from exc


def load_config(path: str | Path) -> ReconConfig:
    """Read a YAML job file with ``yaml.safe_load`` (no arbitrary object construction)."""
    p = Path(path)
    if not p.is_file():
        raise ConfigurationError(f"configuration file not found: {p}")
    if p.stat().st_size > MAX_CONFIG_BYTES:
        raise ConfigurationError(f"configuration file is larger than {MAX_CONFIG_BYTES} bytes")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"could not parse YAML in {p}: {exc}") from exc
    return config_from_dict(data)
