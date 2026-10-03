"""Synthetic reconciliation pairs with controlled corruption and known ground truth.

Every corruption is applied to a disjoint set of rows so the ground truth stays unambiguous:
each affected key appears in exactly one corruption bucket.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

REGIONS = ["East", "West", "South", "North"]
CHANNELS = ["web", "store", "phone"]
STATUSES = ["open", "shipped", "delivered", "returned"]
FIRST = ["Acme", "Globex", "Initech", "Umbrella", "Stark", "Wayne", "Wonka", "Hooli", "Vandelay"]
SUFFIX = ["Ltd", "Inc", "LLC", "Group", "Co"]


@dataclass
class GroundTruth:
    """What was done to the right-hand dataset."""

    keys: list[str]
    missing_from_right: set[int] = field(default_factory=set)
    missing_from_left: set[int] = field(default_factory=set)
    value_changes: dict[tuple[int, str], str] = field(default_factory=dict)
    """``(key, column) -> corruption kind`` for every changed cell."""
    duplicated_keys: set[int] = field(default_factory=set)
    systematic: dict[str, float] = field(default_factory=dict)
    segment: tuple[str, str] | None = None
    missing_segment: tuple[str, str] | None = None
    incident_days: tuple[int, int] | None = None
    incident_dates: tuple[str, str] | None = None
    schema: dict[str, Any] = field(default_factory=dict)

    def changed_cells(self, kinds: set[str] | None = None) -> set[tuple[int, str]]:
        return {k for k, v in self.value_changes.items() if kinds is None or v in kinds}

    def to_dict(self) -> dict[str, Any]:
        kinds: dict[str, int] = {}
        for v in self.value_changes.values():
            kinds[v] = kinds.get(v, 0) + 1
        return {
            "missing_from_right": len(self.missing_from_right),
            "missing_from_left": len(self.missing_from_left),
            "changed_cells": kinds,
            "duplicated_keys": len(self.duplicated_keys),
            "systematic": self.systematic,
            "segment": self.segment,
            "missing_segment": self.missing_segment,
            "incident_dates": self.incident_dates,
            "schema": self.schema,
        }


@dataclass
class SyntheticPair:
    left: pd.DataFrame
    right: pd.DataFrame
    truth: GroundTruth

    @property
    def keys(self) -> list[str]:
        return self.truth.keys


def generate_base(
    rows: int, *, days: int = 30, start: str = "2026-09-01", seed: int = 0
) -> pd.DataFrame:
    """A realistic order-level table: ids, dates, categories, amounts, text and timestamps."""
    rng = np.random.default_rng(seed)
    customers = [f"{a} {b}" for a in FIRST for b in SUFFIX]
    day = rng.integers(0, days, rows)
    dates = pd.Timestamp(start) + pd.to_timedelta(np.sort(day), unit="D")
    quantity = rng.integers(1, 11, rows)
    unit_price = rng.lognormal(3.2, 0.6, rows).round(2)
    seconds = rng.integers(0, 86_400, rows)
    frame = pd.DataFrame(
        {
            "order_id": np.arange(1, rows + 1),
            "date": dates,
            "region": rng.choice(REGIONS, rows, p=[0.3, 0.25, 0.25, 0.2]),
            "channel": rng.choice(CHANNELS, rows, p=[0.5, 0.35, 0.15]),
            "product": [f"P{p:02d}" for p in rng.integers(1, 21, rows)],
            "customer": rng.choice(customers, rows),
            "status": rng.choice(STATUSES, rows, p=[0.1, 0.3, 0.55, 0.05]),
            "quantity": quantity,
            "unit_price": unit_price,
            "revenue": (quantity * unit_price).round(2),
            "updated_at": dates + pd.to_timedelta(seconds, unit="s"),
        }
    )
    return frame


class _Pool:
    """Draw disjoint row positions."""

    def __init__(self, positions: np.ndarray, rng: np.random.Generator) -> None:
        self.available = rng.permutation(positions)
        self.cursor = 0

    def take(self, n: int, mask: np.ndarray | None = None) -> np.ndarray:
        rest = self.available[self.cursor :]
        if mask is not None:
            chosen = rest[mask[rest]][:n]
            # Keep the remaining positions in their shuffled order.
            others = rest[~np.isin(rest, chosen)]
            self.available = np.concatenate([self.available[: self.cursor], chosen, others])
        else:
            chosen = rest[:n]
        self.cursor += len(chosen)
        return np.asarray(chosen)


def generate_reconciliation_pair(
    rows: int = 10_000,
    *,
    missing_rate: float = 0.0,
    extra_rate: float = 0.0,
    mismatch_rate: float = 0.0,
    duplicate_rate: float = 0.0,
    rounding_rate: float = 0.0,
    timestamp_shift_rate: float = 0.0,
    timestamp_shift: str = "5h30min",
    category_change_rate: float = 0.0,
    string_format_rate: float = 0.0,
    bias: float = 0.0,
    bias_segment: tuple[str, str] | None = None,
    missing_segment: tuple[str, str] | None = None,
    incident_days: tuple[int, int] | None = None,
    incident_rate: float = 0.25,
    schema_changes: bool = False,
    days: int = 30,
    seed: int = 0,
) -> SyntheticPair:
    """Create ``left`` and a corrupted copy ``right`` with full ground truth.

    Rates are fractions of ``rows``. ``bias`` multiplies revenue by ``1 + bias`` for every row (or
    only rows in ``bias_segment``). ``missing_segment`` drops the missing rows from one segment
    only. ``incident_days=(start, end)`` corrupts revenue at ``incident_rate`` on those days.
    """
    rng = np.random.default_rng(seed + 1)
    left = generate_base(rows, days=days, seed=seed)
    right = left.copy()
    truth = GroundTruth(keys=["order_id"])
    ids = left["order_id"].to_numpy()
    pool = _Pool(np.arange(rows), rng)

    def count(rate: float) -> int:
        return round(rate * rows)

    # Systematic bias first: it touches every eligible row, so other corruptions avoid them.
    if bias:
        if bias_segment:
            col, level = bias_segment
            eligible = np.flatnonzero((left[col] == level).to_numpy())
            truth.segment = bias_segment
        else:
            eligible = np.arange(rows)
        n_bias = len(eligible) if bias_segment else rows
        biased = pool.take(n_bias, np.isin(np.arange(rows), eligible))
        right.loc[biased, "revenue"] = (left.loc[biased, "revenue"] * (1 + bias)).round(2)
        changed = biased[(right.loc[biased, "revenue"] != left.loc[biased, "revenue"]).to_numpy()]
        for i in changed:
            truth.value_changes[(int(ids[i]), "revenue")] = "bias"
        truth.systematic["revenue"] = bias

    if incident_days is not None:
        lo, hi = incident_days
        start = left["date"].min()
        day_index = ((left["date"] - start).dt.days).to_numpy()
        in_window = (day_index >= lo) & (day_index < hi)
        n_inc = round(incident_rate * in_window.sum())
        hit = pool.take(n_inc, in_window)
        factor = 1 + rng.uniform(0.05, 0.3, len(hit)) * rng.choice([-1, 1], len(hit))
        right.loc[hit, "revenue"] = (left.loc[hit, "revenue"] * factor).round(2)
        for i in hit:
            truth.value_changes[(int(ids[i]), "revenue")] = "incident"
        truth.incident_days = incident_days
        truth.incident_dates = (
            str((start + pd.Timedelta(days=lo)).date()),
            str((start + pd.Timedelta(days=hi)).date()),
        )

    if mismatch_rate:
        hit = pool.take(count(mismatch_rate))
        cols = rng.choice(["revenue", "quantity", "status"], len(hit), p=[0.6, 0.25, 0.15])
        for i, col in zip(hit, cols, strict=True):
            # Random direction, so plain value errors carry no systematic bias.
            up = bool(rng.random() < 0.5)
            if col == "revenue":
                scale = float(rng.uniform(1.05, 1.5))
                value = float(left.loc[i, "revenue"]) * (scale if up else 1 / scale)
                right.loc[i, "revenue"] = round(value, 2)
            elif col == "quantity":
                q = int(left.loc[i, "quantity"])
                step = int(rng.integers(1, 4))
                right.loc[i, "quantity"] = q + step if up or q <= step else q - step
            else:
                options = [s for s in STATUSES if s != left.loc[i, "status"]]
                right.loc[i, "status"] = str(rng.choice(options))
            truth.value_changes[(int(ids[i]), str(col))] = "value"

    if rounding_rate:
        hit = pool.take(count(rounding_rate))
        rounded = left.loc[hit, "revenue"].round(0)
        right.loc[hit, "revenue"] = rounded
        for i in hit[(rounded != left.loc[hit, "revenue"]).to_numpy()]:
            truth.value_changes[(int(ids[i]), "revenue")] = "rounding"

    if timestamp_shift_rate:
        hit = pool.take(count(timestamp_shift_rate))
        right.loc[hit, "updated_at"] = left.loc[hit, "updated_at"] + pd.Timedelta(timestamp_shift)
        for i in hit:
            truth.value_changes[(int(ids[i]), "updated_at")] = "timestamp_shift"

    if category_change_rate:
        hit = pool.take(count(category_change_rate))
        for i in hit:
            options = [r for r in CHANNELS if r != left.loc[i, "channel"]]
            right.loc[i, "channel"] = str(rng.choice(options))
            truth.value_changes[(int(ids[i]), "channel")] = "category"

    if string_format_rate:
        hit = pool.take(count(string_format_rate))
        right.loc[hit, "customer"] = " " + left.loc[hit, "customer"].str.upper()
        for i in hit:
            truth.value_changes[(int(ids[i]), "customer")] = "string_format"

    drop: np.ndarray = np.array([], dtype=int)
    if missing_rate:
        mask = None
        if missing_segment:
            col, level = missing_segment
            mask = (left[col] == level).to_numpy()
            truth.missing_segment = missing_segment
        drop = pool.take(count(missing_rate), mask)
        truth.missing_from_right = {int(ids[i]) for i in drop}

    dup_rows = pd.DataFrame()
    if duplicate_rate:
        hit = pool.take(count(duplicate_rate))
        dup_rows = right.loc[hit].copy()
        truth.duplicated_keys = {int(ids[i]) for i in hit}

    right = right.drop(index=drop)
    if extra_rate:
        n_extra = count(extra_rate)
        extra = generate_base(n_extra, days=days, seed=seed + 99)
        extra["order_id"] = np.arange(rows + 1, rows + 1 + n_extra)
        truth.missing_from_left = set(extra["order_id"].tolist())
        right = pd.concat([right, extra], ignore_index=True)
    if not dup_rows.empty:
        right = pd.concat([right, dup_rows], ignore_index=True)

    if schema_changes:
        right["discount"] = 0.0
        right = right.drop(columns=["status"]).rename(columns={"quantity": "qty"})
        truth.schema = {
            "added": ["discount"],
            "removed": ["status"],
            "renamed": {"quantity": "qty"},
        }
        for key in [k for k, v in truth.value_changes.items() if k[1] in ("status", "quantity")]:
            truth.value_changes.pop(key)

    right = right.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    return SyntheticPair(left=left, right=right, truth=truth)
