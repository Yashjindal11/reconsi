from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from reconsi.cli.main import contained_path, main
from reconsi.core.errors import ConfigurationError


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    a = pd.DataFrame(
        {"id": [1, 2, 3], "country": ["India", "USA", "UK"], "amount": [100, 200, 300]}
    )
    b = pd.DataFrame(
        {"id": [1, 2, 4], "country": ["India", "USA", "Canada"], "amount": [100, 250, 400]}
    )
    a.to_csv(tmp_path / "a.csv", index=False)
    b.to_parquet(tmp_path / "b.parquet")
    return tmp_path / "a.csv", tmp_path / "b.parquet"


def test_compare_one_command_writes_default_report(
    files: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    code = main(["compare", str(files[0]), str(files[1]), "--keys", "id"])
    out = capsys.readouterr().out
    assert code == 1
    assert "Status   FAIL" in out and "missing from right" in out
    assert (tmp_path / "reconsi-report.html").exists()


def test_compare_spec_style_flags_and_outputs(files: tuple[Path, Path], tmp_path: Path) -> None:
    out = tmp_path / "out"
    code = main(
        [
            "compare",
            "--left",
            str(files[0]),
            "--right",
            str(files[1]),
            "--keys",
            "id",
            "--output",
            str(out / "report.html"),
            "--json",
            str(out / "result.json"),
            "--markdown",
            str(out / "report.md"),
            "--export-dir",
            str(out / "evidence"),
            "--fail-on",
            "never",
            "--quiet",
        ]
    )
    assert code == 0
    doc = json.loads((out / "result.json").read_text())
    assert doc["summary"]["missing_left"] == 1
    assert (out / "report.md").read_text().startswith("# Reconciliation report")
    assert pd.read_csv(out / "evidence" / "missing_left.csv")["id"].tolist() == [4]


def test_compare_thresholds_and_fail_on_warning(files: tuple[Path, Path], tmp_path: Path) -> None:
    args = [
        "compare",
        str(files[0]),
        str(files[1]),
        "-k",
        "id",
        "--max-missing",
        "5",
        "--max-mismatch-pct",
        "60",
        "--no-report",
        "-q",
    ]
    assert main(args) == 0
    assert main([*args, "--fail-on", "warning"]) == 1


def test_compare_mapping_tolerance_and_aggregation(tmp_path: Path) -> None:
    tx = pd.DataFrame({"day": ["d1", "d1", "d2"], "amt": [1.0, 2.0, 3.0]})
    daily = pd.DataFrame({"date": ["d1", "d2"], "revenue": [3.004, 3.0], "orders": [2, 1]})
    tx.to_csv(tmp_path / "tx.csv", index=False)
    daily.to_csv(tmp_path / "daily.csv", index=False)
    code = main(
        [
            "compare",
            str(tmp_path / "tx.csv"),
            str(tmp_path / "daily.csv"),
            "--group-by-left",
            "day",
            "--right-keys",
            "date",
            "--agg",
            "revenue=sum",
            "--agg",
            "orders=count",
            "--map",
            "revenue=revenue",
            "--abs-tol",
            "0.01",
            "--no-report",
            "-q",
        ]
    )
    assert code == 2  # revenue does not exist on the left: a configuration error, exit 2
    tx = tx.rename(columns={"amt": "revenue"})
    tx.to_csv(tmp_path / "tx.csv", index=False)
    code = main(
        [
            "compare",
            str(tmp_path / "tx.csv"),
            str(tmp_path / "daily.csv"),
            "--group-by-left",
            "day",
            "--right-keys",
            "date",
            "--agg",
            "revenue=sum",
            "--agg",
            "orders=count",
            "--abs-tol",
            "0.01",
            "--no-report",
            "-q",
        ]
    )
    assert code == 0


def test_compare_requires_keys_and_two_datasets(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["compare", str(files[0]), str(files[1])]) == 2
    assert "--keys is required" in capsys.readouterr().err
    assert main(["compare", str(files[0]), "-k", "id"]) == 2
    assert main(["compare", str(files[0]), "nope.csv", "-k", "id"]) == 2


def _job(tmp_path: Path, files: tuple[Path, Path], extra: str = "") -> Path:
    path = tmp_path / "job.yaml"
    path.write_text(
        f"""
name: demo
left: {{path: {files[0].name}}}
right: {{path: {files[1].name}}}
keys: [id]
thresholds: {{max_missing_records: 2, max_mismatch_percentage: 60}}
output:
  html: out/report.html
  json: out/result.json
{extra}
"""
    )
    return path


def test_run_validate_report_history_diff(
    files: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, files, "history: {path: .reconsi/history.db}")
    assert main(["validate", str(job)]) == 0
    assert "valid" in capsys.readouterr().out
    assert main(["run", str(job), "-q"]) == 0
    assert (tmp_path / "out" / "report.html").exists()
    doc = json.loads((tmp_path / "out" / "result.json").read_text())
    assert doc["status"] == "PASS_WITH_WARNINGS"
    assert main(["run", str(job), "-q"]) == 0
    db = tmp_path / ".reconsi" / "history.db"
    capsys.readouterr()
    assert main(["history", "--path", str(db), "--json"]) == 0
    runs = json.loads(capsys.readouterr().out)
    assert len(runs) == 2 and runs[0]["name"] == "demo"
    assert main(["history", "--path", str(db)]) == 0
    capsys.readouterr()
    assert main(["diff", runs[1]["run_id"], runs[0]["run_id"], "--history", str(db)]) == 0
    assert "Status: PASS_WITH_WARNINGS -> PASS_WITH_WARNINGS" in capsys.readouterr().out
    assert (
        main(["report", runs[0]["run_id"], "--history", str(db), "-o", str(tmp_path / "r.md")]) == 0
    )
    assert (
        main(["report", str(tmp_path / "out" / "result.json"), "-o", str(tmp_path / "r.html")]) == 0
    )
    assert (tmp_path / "r.html").read_text().startswith("<!DOCTYPE html>")
    assert (
        main(
            [
                "diff",
                str(tmp_path / "out" / "result.json"),
                str(tmp_path / "out" / "result.json"),
                "--json",
            ]
        )
        == 0
    )


def test_validate_reports_problems(
    files: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("keys: [id]\nleft: {path: missing.csv}\noutput: {html: ../../escape.html}\n")
    assert main(["validate", str(bad)]) == 2
    out = capsys.readouterr().out
    assert "left: Input file not found" in out and "right: no dataset" in out and "escapes" in out
    broken = tmp_path / "broken.yaml"
    broken.write_text("keys: []\n")
    assert main(["validate", str(broken)]) == 2


def test_contained_path(tmp_path: Path) -> None:
    assert contained_path("a/b.html", tmp_path) == (tmp_path / "a" / "b.html").resolve()
    with pytest.raises(ConfigurationError):
        contained_path("../x.html", tmp_path)
    with pytest.raises(ConfigurationError):
        contained_path("/etc/x.html", tmp_path)


def test_schema_and_inspect(files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema", str(files[0]), str(files[1])]) == 0
    assert "identical" in capsys.readouterr().out
    assert main(["schema", str(files[0]), str(files[1]), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["left"]["column_count"] == 3
    assert main(["inspect", str(files[0]), "-k", "id"]) == 0
    out = capsys.readouterr().out
    assert "grain (inferred): id" in out and "3 unique" in out
    assert main(["inspect", str(files[0]), "--json"]) == 0
    assert main(["inspect", str(files[0]), "-k", "nope"]) == 2


def test_history_missing_and_diff_unknown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["history", "--path", str(tmp_path / "none.db")]) == 0
    assert "no history" in capsys.readouterr().out
    assert main(["diff", "x", "y", "--history", str(tmp_path / "none.db")]) == 2


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "reconsi" in capsys.readouterr().out
