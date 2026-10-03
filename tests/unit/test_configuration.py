from __future__ import annotations

from pathlib import Path

import pytest

from reconsi.configuration import ReconConfig, config_from_dict, load_config
from reconsi.core.errors import ConfigurationError

SPEC_EXAMPLE = """
name: daily_sales_reconciliation

left:
  path: sales_system_a.parquet

right:
  path: sales_system_b.parquet

keys:
  - date
  - store_id
  - product_id

columns:
  revenue:
    type: numeric
    absolute_tolerance: 0.01

  quantity:
    type: numeric
    absolute_tolerance: 0

rules:
  max_mismatch_percentage: 0.1
"""


def test_spec_example_parses(tmp_path: Path) -> None:
    path = tmp_path / "job.yaml"
    path.write_text(SPEC_EXAMPLE)
    cfg = load_config(path)
    assert cfg.keys == ["date", "store_id", "product_id"]
    assert cfg.left is not None and cfg.left.path == "sales_system_a.parquet"
    assert cfg.thresholds.max_mismatch_percentage == 0.1
    assert cfg.column_options("revenue").absolute_tolerance == 0.01
    assert cfg.column_options("other").absolute_tolerance == 0.0


def test_keys_resolution_with_mapping_and_group_by() -> None:
    cfg = ReconConfig(keys=["customer_id"], column_mapping={"customer_id": "cust_id"})
    assert cfg.resolved_left_keys == ["customer_id"]
    assert cfg.resolved_right_keys == ["cust_id"]
    cfg = ReconConfig(left_group_by=["date"], right_keys=["day"], aggregations={"revenue": "sum"})
    assert cfg.keys == ["date"] and cfg.resolved_right_keys == ["day"]
    cfg = ReconConfig(right_keys=["id"])
    assert cfg.keys == ["id"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({}, "key column"),
        ({"keys": ["a"], "right_keys": ["a", "b"]}, "same number"),
        ({"keys": ["a", "a"]}, "duplicate key"),
        ({"keys": ["a"], "left_group_by": ["a"]}, "aggregations"),
        ({"keys": ["a"], "unknown": 1}, "Extra inputs"),
        ({"keys": ["a"], "rules": [{"name": "r"}]}, "metric"),
        ({"keys": ["a"], "rules": [{"name": "r", "metric": "column_mismatches"}]}, "column"),
        ({"keys": ["a"], "rules": [{"name": "r", "column": "a"}]}, "key column"),
        ({"keys": ["a"], "duplicate_strategy": "magic"}, "duplicate_strategy"),
        ({"keys": ["a"], "aggregations": {"x": "exec"}}, "aggregations"),
        ({"keys": ["a"], "thresholds": {"max_mismatch_percentage": 150}}, "less than"),
    ],
)
def test_invalid_configs(data: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        config_from_dict(data)


def test_rule_column_options_merge_into_column() -> None:
    cfg = config_from_dict(
        {
            "keys": ["id"],
            "defaults": {"normalize": ["trim"]},
            "columns": {"name": {"normalize": ["trim", "casefold"]}},
            "rules": [
                {
                    "name": "revenue_match",
                    "column": "revenue",
                    "type": "numeric",
                    "absolute_tolerance": 0.01,
                }
            ],
        }
    )
    assert cfg.column_options("revenue").absolute_tolerance == 0.01
    assert cfg.column_options("revenue").type == "numeric"
    assert cfg.column_options("name").normalize == ["trim", "casefold"]
    assert cfg.column_options("city").normalize == ["trim"]
    assert cfg.rules[0].effective_metric == "column_mismatches"


def test_yaml_is_loaded_safely(tmp_path: Path) -> None:
    path = tmp_path / "evil.yaml"
    path.write_text("keys: !!python/object/apply:os.system ['echo hacked']\n")
    with pytest.raises(ConfigurationError, match="could not parse"):
        load_config(path)


def test_missing_and_non_mapping_config(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="not found"):
        load_config(tmp_path / "nope.yaml")
    path = tmp_path / "list.yaml"
    path.write_text("- a\n- b\n")
    with pytest.raises(ConfigurationError, match="mapping"):
        load_config(path)


def test_output_json_alias() -> None:
    cfg = config_from_dict({"keys": ["a"], "output": {"json": "out.json", "html": "r.html"}})
    assert cfg.output is not None and cfg.output.json_path == "out.json"
