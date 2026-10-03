"""Run every example (used by CI). Fails if any example raises."""

from __future__ import annotations

import runpy
import sys
import time
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def main() -> int:
    sys.path.insert(0, str(EXAMPLES))
    failures = 0
    for path in sorted(EXAMPLES.glob("[0-9][0-9]_*.py")):
        t = time.perf_counter()
        print(f"=== {path.name}", flush=True)
        try:
            runpy.run_path(str(path), run_name="__main__")
        except Exception as exc:
            failures += 1
            print(f"FAILED {path.name}: {exc!r}", flush=True)
        print(f"--- {path.name}: {time.perf_counter() - t:.1f}s\n", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
