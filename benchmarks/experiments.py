"""Research experiments behind docs/research.md.

    python benchmarks/experiments.py            # full run, writes docs/research.md
    python benchmarks/experiments.py --quick    # CI smoke run (few trials, no docs)

Every number in docs/research.md comes from this script. The experiments are simulations with
stated assumptions; they are not claims about any particular real-world dataset.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from reconsi import __version__, reconcile
from reconsi.comparison.records import DIM_PREFIX, STATUS
from reconsi.statistics.bias import detect_bias
from reconsi.statistics.concentration import concentration
from reconsi.synthetic import generate_base
from reconsi.temporal.changepoint import detect_change_points

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmarks" / "results"


# --------------------------------------------------------------------------- E1
def e1_aggregation(trials: int, rows: int) -> pd.DataFrame:
    """Order-level vs daily summary: how many days does each approach flag?"""
    out = []
    for bad_days in (0, 1, 3):
        for seed in range(trials):
            rng = np.random.default_rng(seed)
            tx = generate_base(rows, days=30, seed=seed)
            daily = tx.groupby("date", as_index=False).agg(revenue=("revenue", "sum"))
            bad = rng.choice(len(daily), bad_days, replace=False)
            daily.loc[bad, "revenue"] += rng.uniform(50, 500, bad_days).round(2)
            strict = reconcile(tx, daily, keys="date", compare_columns=["revenue"])
            first = reconcile(
                tx, daily, keys="date", compare_columns=["revenue"], duplicate_strategy="first"
            )
            aware = reconcile(
                tx,
                daily,
                left_group_by=["date"],
                aggregations={"revenue": "sum"},
                absolute_tolerance=0.01,
            )
            diag = strict.analyses.get("aggregation_diagnosis", {})
            out.append(
                {
                    "bad_days": bad_days,
                    "seed": seed,
                    "naive_first_flagged_days": first.summary["value_mismatch_records"],
                    "aggregation_aware_flagged_days": aware.summary["value_mismatch_records"],
                    "diagnosis_says_grain_explains": bool(diag.get("explained_by_grain")),
                }
            )
    return pd.DataFrame(out)


# --------------------------------------------------------------------------- E2
def e2_bias(trials: int) -> pd.DataFrame:
    """Power and false-positive rate of the systematic-difference detector."""
    out = []
    rng = np.random.default_rng(42)
    for n in (10, 25, 50, 100, 500):
        for kind in ("random", "systematic", "mixed_70_30", "mixed_60_40"):
            hits = 0
            for _ in range(trials):
                base = rng.lognormal(4, 0.5, n)
                if kind == "random":
                    diff = rng.normal(0, 0.05, n) * base
                elif kind == "systematic":
                    diff = base * 0.025 * rng.uniform(0.8, 1.2, n)
                else:
                    share = 0.7 if kind == "mixed_70_30" else 0.6
                    m = round(share * n)
                    diff = np.concatenate([base[:m] * 0.025, rng.normal(0, 0.05, n - m) * base[m:]])
                hits += detect_bias(diff, diff / base)["systematic"]
            out.append({"differing_pairs": n, "scenario": kind, "flagged_rate": hits / trials})
    return pd.DataFrame(out)


# --------------------------------------------------------------------------- E3
def e3_concentration(trials: int, rows: int) -> pd.DataFrame:
    """Does concentration analysis point at the segment whose mismatch rate was raised?"""
    out = []
    rng = np.random.default_rng(7)
    regions = np.array(["East", "West", "South", "North"])
    for multiplier in (1.0, 1.5, 2.0, 3.0, 5.0):
        correct = flagged_any = 0
        for _ in range(trials):
            region = rng.choice(regions, rows)
            rate = np.where(region == "West", 0.01 * multiplier, 0.01)
            problem = rng.random(rows) < rate
            records = pd.DataFrame(
                {
                    STATUS: np.where(problem, "value_mismatch", "matched"),
                    DIM_PREFIX + "region": region,
                    DIM_PREFIX + "channel": rng.choice(["web", "store", "phone"], rows),
                }
            )
            res = {c["dimension"]: c for c in concentration(records, ["region", "channel"])}
            flagged = [c for c in res.values() if c["concentrated"]]
            flagged_any += bool(flagged)
            correct += bool(
                res["region"]["concentrated"] and res["region"]["top_level"]["level"] == "West"
            )
        out.append(
            {
                "segment_rate_multiplier": multiplier,
                "correct_segment_rate": correct / trials,
                "any_flag_rate": flagged_any / trials,
            }
        )
    return pd.DataFrame(out)


# --------------------------------------------------------------------------- E4
def e4_change_points(trials: int) -> pd.DataFrame:
    """Recall of incident boundaries and false alarms on stable series."""
    out = []
    rng = np.random.default_rng(3)
    days, per_day, base = 30, 500, 0.01
    for multiplier in (1.0, 1.5, 2.0, 3.0, 5.0):
        both = spurious = 0
        for t in range(trials):
            rates = np.full(days, base)
            if multiplier > 1:
                rates[12:16] = base * multiplier
            k = rng.binomial(per_day, rates)
            cps = [int(c["index"]) for c in detect_change_points(k, np.full(days, per_day), seed=t)]
            if multiplier > 1:
                both += any(abs(c - 12) <= 1 for c in cps) and any(abs(c - 16) <= 1 for c in cps)
                spurious += sum(1 for c in cps if min(abs(c - 12), abs(c - 16)) > 1)
            else:
                spurious += len(cps)
        out.append(
            {
                "incident_rate_multiplier": multiplier,
                "both_boundaries_found": both / trials if multiplier > 1 else None,
                "spurious_change_points_per_series": spurious / trials,
            }
        )
    return pd.DataFrame(out)


# --------------------------------------------------------------------------- output
def _table(frame: pd.DataFrame, fmt: dict[str, str]) -> str:
    cols = list(frame.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, row in frame.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            if v is None or (isinstance(v, float) and np.isnan(v)):
                cells.append("n/a")
            elif c in fmt:
                cells.append(format(v, fmt[c]))
            elif isinstance(v, float) and v.is_integer():
                cells.append(f"{int(v):,}")
            elif isinstance(v, int):
                cells.append(f"{v:,}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render(results: dict[str, Any], meta: dict[str, Any]) -> str:
    e1 = (
        results["e1"]
        .groupby("bad_days")
        .agg(
            trials=("seed", "count"),
            naive_first_flagged_days=("naive_first_flagged_days", "mean"),
            aggregation_aware_flagged_days=("aggregation_aware_flagged_days", "mean"),
            diagnosis_says_grain_explains=("diagnosis_says_grain_explains", "mean"),
        )
        .reset_index()
    )
    e2 = (
        results["e2"]
        .pivot(index="differing_pairs", columns="scenario", values="flagged_rate")
        .reset_index()
    )
    e2.columns.name = None
    scale = ""
    scale_path = RESULTS / "scale.json"
    if scale_path.exists():
        data = json.loads(scale_path.read_text())
        rows = [r for r in data["runs"] if "seconds" in r]
        frame = pd.DataFrame(rows)[["rows", "backend", "seconds", "rows_per_second", "peak_rss_mb"]]
        scale = (
            f"Machine: {data['machine'].get('cpu')}, "
            f"{int(data['machine'].get('memory_bytes', 0)) / 2**30:.0f} GB RAM, Python "
            f"{data['machine']['python']}, pandas {data['machine']['pandas']}, DuckDB "
            f"{data['machine']['duckdb']}.\n\n"
            + _table(frame, {"seconds": ".2f", "rows_per_second": ",.0f", "peak_rss_mb": ",.0f"})
        )
        failed = [r for r in data["runs"] if "error" in r]
        if failed:
            scale += "\n\nRuns that did not complete: " + "; ".join(
                f"{r['rows']:,} rows on {r['backend']} ({r['error']})" for r in failed
            )
    return f"""# Research notes

Generated by `python benchmarks/experiments.py` (ReconSI {meta["version"]}, {meta["seconds"]:.0f}s).
These are simulation studies with stated assumptions. They describe how ReconSI's diagnostics
behave on synthetic data; they are not claims about any particular real-world dataset.

## R1. How much does aggregation-aware comparison reduce false mismatch reports?

Setup: {meta["e1_rows"]:,} order-level rows over 30 days (left) against a daily revenue summary
(right) in which `bad_days` days were altered by 50-500. Compared: naively keeping the first
order per day (`duplicate_strategy="first"`), grain-aware (`left_group_by=["date"]`), and the
default `strict` strategy, which sets the duplicated days aside instead of guessing and runs the
aggregation diagnosis.

{_table(e1, {"naive_first_flagged_days": ".1f", "aggregation_aware_flagged_days": ".1f", "diagnosis_says_grain_explains": ".0%"})}

Reading: the naive comparison flags essentially every day because one order is not a daily total;
the grain-aware comparison flags exactly the altered days. With no altered days the strict
strategy's diagnosis states that grain explains the differences; once a day is altered it
correctly reports that differences persist after aggregation.

## R2. Can statistical evidence distinguish systematic from random discrepancies?

Setup: `detect_bias` (exact sign test, alpha 0.01, at least 75% of differing pairs in one
direction) on simulated differences, {meta["trials"]} trials per cell. `random` = symmetric noise
(the false-positive rate); `systematic` = every pair 2.5% higher (+/-20%); `mixed_a_b` = a% of pairs
systematic and b% random noise.

{_table(e2, {c: ".0%" for c in e2.columns if c != "differing_pairs"})}

Reading: pure systematic shifts are detected from as few as 10 differing pairs. In mixed
populations the random pairs still split about evenly, so a 60/40 mix has roughly 80% of pairs
in one direction: it is missed at small n and reliably flagged from about 100 pairs. The
false-positive rate on random noise stays at or below the 1% test level.

## R3. Can mismatch concentration reveal an upstream failure in one segment?

Setup: {meta["e3_rows"]:,} records, base problem rate 1%, the `West` region (25% of records) has its
rate multiplied; a second, unrelated dimension is also tested. {meta["trials_small"]} trials per row.
"Correct" = region flagged as concentrated with `West` as the top level (chi-square with
Bonferroni correction, lift >= 1.5, at least 5 problem records).

{_table(results["e3"], {"correct_segment_rate": ".0%", "any_flag_rate": ".0%"})}

Reading: the multiplier-1.0 row is the false-alarm rate. A segment with double the base rate
is usually found at this volume; a 1.5x increase often is not, which is the intended trade-off
for avoiding false alarms.

## R4. How reliably are changes in the mismatch rate located in time?

Setup: 30 daily periods of 500 records, base problem rate 1%, an incident multiplies the rate on
days 12-15. Circular binary segmentation with a permutation test (alpha 0.01). A detection
requires change points within one day of both boundaries. {meta["trials_small"]} trials per row.

{_table(results["e4"], {"both_boundaries_found": ".0%", "spurious_change_points_per_series": ".2f"})}
Reading: with 500 records per day, a four-day incident at 3x the base rate is located in most
series and at 5x almost always; at 1.5x-2x it usually is not. False alarms stay rare (a few per
hundred stable series), consistent with the 1% permutation-test level.
## R5. How does reconciliation scale with dataset size?

From `python benchmarks/bench_scale.py` (wall time of `reconcile()` on two Parquet files with
2% missing, 1% extra and 0.5% mismatched rows; peak resident memory of a fresh process;
throughput counts rows on both sides). Single runs, so treat small differences as noise.

{scale or "_Run `python benchmarks/bench_scale.py` to populate this section._"}

Reading: both backends stream the joined rows through the same Python comparison code, so
comparison work dominates and the backends perform similarly; the DuckDB backend's benefit is
that loading, de-duplication, aggregation and the join itself run out of core. Pushing simple
comparisons into SQL is the obvious next step and is not done yet.

## Open questions

- Root-cause ranking: findings are currently ordered by severity; learning a ranking from
  labelled incidents would need real incident data.
- Multi-dimension concentration (region x product) is available through `drill_down` but is not
  tested automatically, to avoid a combinatorial number of tests.
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument(
        "--render-only", action="store_true", help="rewrite docs/research.md from saved results"
    )
    args = parser.parse_args()
    if args.render_only:
        saved = json.loads((RESULTS / "experiments.json").read_text())
        frames = {k: pd.DataFrame(saved[k]) for k in ("e1", "e2", "e3", "e4")}
        (ROOT / "docs" / "research.md").write_text(render(frames, saved["meta"]))
        print("wrote docs/research.md")
        return
    trials = 5 if args.quick else 200
    small = 5 if args.quick else 100
    t0 = time.perf_counter()
    meta = {
        "version": __version__,
        "trials": trials,
        "trials_small": small,
        "e1_rows": 2_000 if args.quick else 20_000,
        "e3_rows": 20_000,
    }
    results = {
        "e1": e1_aggregation(2 if args.quick else 5, meta["e1_rows"]),
        "e2": e2_bias(trials),
        "e3": e3_concentration(small, meta["e3_rows"]),
        "e4": e4_change_points(small),
    }
    meta["seconds"] = time.perf_counter() - t0
    RESULTS.mkdir(exist_ok=True)
    name = "experiments-quick.json" if args.quick else "experiments.json"
    (RESULTS / name).write_text(
        json.dumps(
            {"meta": meta, **{k: v.to_dict(orient="records") for k, v in results.items()}},
            indent=1,
            default=str,
        )
    )
    for key, frame in results.items():
        print(f"== {key}")
        print(
            frame.to_string(index=False)
            if key != "e1"
            else frame.groupby("bad_days").mean(numeric_only=True).to_string()
        )
    if not args.quick:
        (ROOT / "docs" / "research.md").write_text(render(results, meta))
        print("wrote docs/research.md")


if __name__ == "__main__":
    main()
