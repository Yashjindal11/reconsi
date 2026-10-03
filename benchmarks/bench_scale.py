"""Scale benchmark: runtime, throughput and peak memory for the pandas and DuckDB backends.

    python benchmarks/bench_scale.py                      # 10K, 100K, 1M rows, both backends
    python benchmarks/bench_scale.py --sizes 10000000 --backends duckdb
    python benchmarks/bench_scale.py --quick              # CI smoke run (10K rows)

Each measurement runs in a fresh subprocess so peak RSS is not polluted by earlier runs. Inputs
are Parquet files produced by the synthetic generator (2% missing, 1% extra, 0.5% value
mismatches). Results are appended to ``benchmarks/results/scale.json``.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

WORKER = r"""
import json, resource, sys, time
t0 = time.perf_counter()
from reconsi import reconcile
import_s = time.perf_counter() - t0
left, right, backend = sys.argv[1:4]
t = time.perf_counter()
r = reconcile(left, right, keys="order_id", backend=backend)
elapsed = time.perf_counter() - t
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
rss_mb = rss / 1e6 if sys.platform == "darwin" else rss / 1e3
print(json.dumps({
    "seconds": elapsed,
    "import_seconds": import_s,
    "peak_rss_mb": rss_mb,
    "matched": r.summary["matched_records"],
    "value_mismatch_records": r.summary["value_mismatch_records"],
    "missing": r.summary["missing_records"],
}))
"""


def machine() -> dict[str, str]:
    info = {"python": platform.python_version(), "platform": platform.platform(terse=True)}
    if sys.platform == "darwin":
        for key, name in (("cpu", "machdep.cpu.brand_string"), ("memory_bytes", "hw.memsize")):
            out = subprocess.run(
                ["sysctl", "-n", name], capture_output=True, text=True, check=False
            )
            info[key] = out.stdout.strip()
    else:
        info["cpu"] = platform.processor()
    import duckdb
    import pandas

    info["pandas"] = pandas.__version__
    info["duckdb"] = duckdb.__version__
    return info


def make_inputs(rows: int, directory: Path) -> tuple[Path, Path]:
    from reconsi.synthetic import generate_reconciliation_pair

    pair = generate_reconciliation_pair(
        rows, missing_rate=0.02, extra_rate=0.01, mismatch_rate=0.005, seed=rows % 997
    )
    left, right = directory / f"left_{rows}.parquet", directory / f"right_{rows}.parquet"
    pair.left.to_parquet(left, index=False)
    pair.right.to_parquet(right, index=False)
    return left, right


def run_one(left: Path, right: Path, backend: str, timeout: int) -> dict[str, object]:
    proc = subprocess.run(
        [sys.executable, "-c", WORKER, str(left), str(right), backend],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-1:] or ["unknown error"]
        return {"error": tail[0], "returncode": proc.returncode}
    return dict(json.loads(proc.stdout.strip().splitlines()[-1]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", default="10000,100000,1000000")
    parser.add_argument("--backends", default="pandas,duckdb")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    sizes = [10_000] if args.quick else [int(s) for s in args.sizes.split(",")]
    backends = args.backends.split(",")
    out_path = RESULTS / ("scale-quick.json" if args.quick else "scale.json")
    RESULTS.mkdir(exist_ok=True)
    existing = json.loads(out_path.read_text()) if out_path.exists() and not args.quick else {}
    runs = list(existing.get("runs", []))
    with tempfile.TemporaryDirectory() as tmp:
        for rows in sizes:
            t = time.perf_counter()
            left, right = make_inputs(rows, Path(tmp))
            print(f"{rows:>12,} rows: inputs ready in {time.perf_counter() - t:.1f}s", flush=True)
            for backend in backends:
                for repeat in range(args.repeats):
                    res = run_one(left, right, backend, args.timeout)
                    res.update({"rows": rows, "backend": backend, "repeat": repeat})
                    if "seconds" in res:
                        res["rows_per_second"] = 2 * rows / float(res["seconds"])  # type: ignore[arg-type]
                        print(
                            f"  {backend:<7} {res['seconds']:8.2f}s  "
                            f"{res['rows_per_second']:>12,.0f} rows/s  peak {res['peak_rss_mb']:8.0f} MB",
                            flush=True,
                        )
                    else:
                        print(f"  {backend:<7} failed: {res['error']}", flush=True)
                    runs = [
                        r
                        for r in runs
                        if (r["rows"], r["backend"], r["repeat"]) != (rows, backend, repeat)
                    ]
                    runs.append(res)
    runs.sort(key=lambda r: (r["rows"], r["backend"], r["repeat"]))
    out_path.write_text(json.dumps({"machine": machine(), "runs": runs}, indent=2))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
