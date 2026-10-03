"""Storage/compute backends.

A backend owns the two tables being reconciled and performs the set-oriented work (loading,
aggregation, de-duplication and the outer join). Value comparison itself is backend-independent:
the join is streamed back in pandas chunks and compared by :mod:`reconsi.comparison`, so every
backend applies identical comparison semantics.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from typing import ClassVar, Literal

import pandas as pd

from reconsi.inputs.sources import TableSource

Side = Literal["left", "right"]
SIDES: tuple[Side, Side] = ("left", "right")
JOIN_STATUS = "_side"
LEFT_PREFIX = "l."
RIGHT_PREFIX = "r."
OCCURRENCE = "_occurrence"
ROW_COUNT = "_row_count"


class TableBackend(ABC):
    name: ClassVar[str]

    @abstractmethod
    def load(
        self,
        side: Side,
        source: TableSource,
        *,
        rename: Mapping[str, str],
        string_columns: list[str],
    ) -> None:
        """Register a dataset. ``rename`` maps source column names to reconciliation names."""

    @abstractmethod
    def columns(self, side: Side) -> list[str]: ...

    @abstractmethod
    def row_count(self, side: Side) -> int: ...

    @abstractmethod
    def head(self, side: Side, n: int) -> pd.DataFrame:
        """First ``n`` rows (used for type inference)."""

    @abstractmethod
    def null_counts(self, side: Side) -> dict[str, int]: ...

    @abstractmethod
    def fetch(self, side: Side, columns: list[str]) -> pd.DataFrame:
        """All rows of the selected columns."""

    @abstractmethod
    def sample(self, side: Side, columns: list[str], n: int, seed: int) -> pd.DataFrame:
        """A reproducible random sample of at most ``n`` rows."""

    @abstractmethod
    def sums(self, side: Side, columns: list[str]) -> dict[str, float | None]: ...

    @abstractmethod
    def aggregate(self, side: Side, keys: list[str], aggregations: Mapping[str, str]) -> None:
        """Replace the table with ``keys`` + aggregated columns."""

    @abstractmethod
    def deduplicate(self, side: Side, keys: list[str], keep: Literal["first", "last"]) -> int:
        """Keep one row per key by input order. Returns the number of rows removed."""

    @abstractmethod
    def remove_keys(self, side: Side, keys: list[str], key_values: pd.DataFrame) -> pd.DataFrame:
        """Remove rows whose key appears in ``key_values``; return the removed rows."""

    @abstractmethod
    def add_occurrence(self, side: Side, keys: list[str], order_by: list[str]) -> None:
        """Number duplicate rows within each key (``_occurrence``) after sorting by ``order_by``."""

    @abstractmethod
    def cast_keys_to_text(self, side: Side, keys: list[str]) -> None:
        """Convert key columns to canonical text so differently-typed keys can be joined."""

    @abstractmethod
    def normalize_keys(self, side: Side, keys: list[str], steps: list[str]) -> None: ...

    @abstractmethod
    def join(
        self,
        keys: list[str],
        left_columns: list[str],
        right_columns: list[str],
        chunk_size: int,
    ) -> Iterator[pd.DataFrame]:
        """Full outer join on ``keys`` streamed in chunks.

        Each chunk has the key columns, ``_side`` (``both``/``left_only``/``right_only``) and the
        requested value columns prefixed with ``l.`` / ``r.``. Rows with a null key component
        never match (SQL semantics) and are reported as one-sided.
        """

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release resources."""
