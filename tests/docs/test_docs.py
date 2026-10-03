"""Execute every ```python block in README.md and docs/*.md (```py blocks are not run).

Blocks within one file share a namespace and run in order, in a temporary directory.
"""

from __future__ import annotations

import os
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FILES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
BLOCK = re.compile(r"^```python\n(.*?)^```", re.DOTALL | re.MULTILINE)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_python_blocks_run(path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    blocks = BLOCK.findall(path.read_text(encoding="utf-8"))
    if not blocks:
        pytest.skip("no python blocks")
    module = types.ModuleType("reconsi_docs_block")
    sys.modules[module.__name__] = module  # dataclasses look their module up
    namespace = module.__dict__
    cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        for i, code in enumerate(blocks, 1):
            try:
                exec(compile(code, f"{path.name}[block {i}]", "exec"), namespace)
            except Exception as exc:
                raise AssertionError(f"{path.name} block {i} failed: {exc!r}\n{code}") from exc
    finally:
        os.chdir(cwd)
        sys.modules.pop(module.__name__, None)
    capsys.readouterr()
