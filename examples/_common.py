"""Shared helpers for the examples: an output directory that is git-ignored."""

from __future__ import annotations

from pathlib import Path

OUTPUT = Path(__file__).resolve().parent / "output"


def out_dir(name: str) -> Path:
    path = OUTPUT / name
    path.mkdir(parents=True, exist_ok=True)
    return path
