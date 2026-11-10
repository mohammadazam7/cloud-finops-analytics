from pathlib import Path
from typing import Any

import duckdb
import pytest

from finops_analytics import metrics
from finops_analytics.cli import main
from finops_analytics.metrics import Kind, Metric, MetricError, Source


@pytest.fixture
def spec() -> dict[str, Metric]:
    return metrics.load()


@pytest.fixture
def warehouse(tmp_path: Path) -> Path:
    """A tiny warehouse with the mart columns the metric layer reads."""
    path = tmp_path / "wh.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("create schema marts")
        con.execute(
            "create table marts.fct_cost_daily as select * from (values"
            " (date '2025-01-01', 'svc1', 'acc1', 'reg1', 'Usage', 'synthetic_charges',"
            "  10.0, 6.0, 10.0, 8.0, 1),"
            " (date '2025-01-02', 'svc2', 'acc1', 'reg1', 'Usage', 'synthetic_charges',"
            "  30.0, 30.0, 30.0, 30.0, 2)"
            ") t(charge_date, service_key, account_key, region_key, charge_category,"
            " source_dataset, billed_cost, effective_cost, list_cost, contracted_cost, line_count)"
        )
        con.execute(
            "create table marts.dim_service as select * from (values"
            " ('svc1', 'AWS', 'Amazon EC2', 'Compute'),"
            " ('svc2', 'AWS', 'Amazon S3', 'Storage')"
            ") t(service_key, provider_name, service_name, service_category)"
        )
        con.execute(
            "create table marts.dim_account as select 'acc1' as account_key,"
            " 'payments' as team, 'prod' as environment"
        )
        con.execute(
            "create table marts.dim_region as select 'reg1' as region_key, 'us-east-1' as region_id"
        )
        con.execute(
            "create table marts.agg_commitment_daily as select * from (values"
            " (date '2025-01-01', 'AWS', 9.0, 1.0, 10.0, 8.0, 10.0),"
            " (date '2025-01-02', 'AWS', 5.0, 25.0, 30.0, 2.0, 40.0)"
            ") t(charge_date, provider_name, used_cost, unused_cost, committed_cost,"
            " covered_list_cost, eligible_list_cost)"
        )
    return path


def _value(warehouse: Path, query: str) -> list[tuple[Any, ...]]:
    with duckdb.connect(str(warehouse), read_only=True) as con:
        return con.sql(query).fetchall()


def test_spec_loads_and_every_metric_compiles(spec: dict[str, Metric], warehouse: Path) -> None:
    assert {"effective_cost", "commitment_utilization", "commitment_coverage"} <= set(spec)
    for metric in spec.values():
        assert len(_value(warehouse, metrics.sql(metric))) == 1


def test_ratios_are_ratios_of_sums_not_averages(spec: dict[str, Metric], warehouse: Path) -> None:
    # Daily utilizations are 0.9 and 0.17; their average (0.53) would be wrong.
    [(util,)] = _value(warehouse, metrics.sql(spec["commitment_utilization"]))
    assert util == pytest.approx(14 / 40)
    [(coverage,)] = _value(warehouse, metrics.sql(spec["commitment_coverage"]))
    assert coverage == pytest.approx(10 / 50)
    [(savings,)] = _value(warehouse, metrics.sql(spec["effective_savings_rate"]))
    assert savings == pytest.approx(1 - 36 / 40)


def test_group_by_and_filter_join_the_dimensions(spec: dict[str, Metric], warehouse: Path) -> None:
    rows = _value(warehouse, metrics.sql(spec["effective_cost"], group_by=["service_category"]))
    assert [(r[0], float(r[1])) for r in rows] == [("Compute", 6.0), ("Storage", 30.0)]
    query = metrics.sql(spec["effective_cost"], where={"service": "Amazon S3", "team": "payments"})
    assert float(_value(warehouse, query)[0][0]) == 30.0


def test_filters_are_quoted(spec: dict[str, Metric]) -> None:
    query = metrics.sql(spec["effective_cost"], where={"team": "x' or '1'='1"})
    assert "'x'' or ''1''=''1'" in query


def test_unsupported_dimensions_are_rejected(spec: dict[str, Metric]) -> None:
    with pytest.raises(MetricError, match="does not support"):
        metrics.sql(spec["commitment_coverage"], group_by=["team"])
    with pytest.raises(MetricError, match="does not support"):
        metrics.sql(spec["effective_cost"], group_by=["colour"])


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"name": "Bad-Name"}, "lower_snake_case"),
        ({"better": "up"}, "better"),
        ({"numerator": "used_cost"}, "unknown numerator"),
        ({"kind": Kind.SUM, "denominator": "list_cost"}, "no denominator"),
        ({"kind": Kind.RATIO, "denominator": None}, "unknown denominator"),
    ],
)
def test_invalid_definitions_fail(changes: dict[str, object], message: str) -> None:
    base: dict[str, object] = {
        "name": "m",
        "label": "M",
        "source": Source.COST,
        "kind": Kind.RATIO,
        "numerator": "effective_cost",
        "denominator": "list_cost",
        "unit": "share",
        "better": "higher",
        "owner": "FinOps",
        "description": "d",
    }
    with pytest.raises(MetricError, match=message):
        Metric(**(base | changes)).validate()  # type: ignore[arg-type]


def test_duplicate_names_fail(tmp_path: Path) -> None:
    entry = (
        "  - {name: a, label: A, source: cost, kind: sum, numerator: list_cost,"
        " unit: USD, better: neutral, owner: o, description: d}\n"
    )
    path = tmp_path / "m.yml"
    path.write_text("metrics:\n" + entry + entry)
    with pytest.raises(MetricError, match="duplicate"):
        metrics.load(path)


def test_dictionary_is_current(spec: dict[str, Metric]) -> None:
    committed = Path(__file__).parents[1] / "docs" / "metric_dictionary.md"
    assert committed.read_text(encoding="utf-8") == metrics.dictionary(spec)


def test_cli_metric(warehouse: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert main(["metric", "commitment_utilization", "--warehouse", str(warehouse)]) == 0
    assert float(capsys.readouterr().out) == pytest.approx(0.35)
    assert main(["metric", "effective_cost", "--by", "month", "--sql"]) == 0
    assert "group by month" in capsys.readouterr().out
    assert main(["metric", "nope"]) == 2
    out = tmp_path / "dict.md"
    assert main(["metrics", "--out", str(out)]) == 0
    assert out.read_text().startswith("# Metric dictionary")
