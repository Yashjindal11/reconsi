"""Synthetic reconciliation datasets with known ground truth."""

from reconsi.synthetic.generator import (
    GroundTruth,
    SyntheticPair,
    generate_base,
    generate_reconciliation_pair,
)

__all__ = ["GroundTruth", "SyntheticPair", "generate_base", "generate_reconciliation_pair"]
