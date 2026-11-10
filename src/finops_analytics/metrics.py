"""The governed cost metric layer.

Every cost metric is defined once, in ``metrics/metrics.yml``. This module loads and
validates those definitions, turns a metric request into SQL against the marts, and
renders the metric dictionary, so a dashboard, a report and an ad hoc query all compute
a metric the same way.

Every metric is a sum or a ratio of sums over additive columns, which keeps it correct
at any grain: a monthly utilization is total used over total committed for the month,
never an average of daily utilizations.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

SPEC_PATH = Path(__file__).resolve().parents[2] / "metrics" / "metrics.yml"


class Kind(Enum):
    SUM = "sum"
    RATIO = "ratio"
    SAVINGS = "savings"


class Source(Enum):
    COST = "cost"
    COMMITMENT = "commitment"


# Additive columns each source exposes.
COMPONENTS: Mapping[Source, frozenset[str]] = {
    Source.COST: frozenset(
        {"billed_cost", "effective_cost", "list_cost", "contracted_cost", "line_count"}
    ),
    Source.COMMITMENT: frozenset(
        {"used_cost", "unused_cost", "committed_cost", "covered_list_cost", "eligible_list_cost"}
    ),
}

# Dimension -> SQL expression in each source that supports it.
DIMENSIONS: Mapping[str, Mapping[Source, str]] = {
    "date": {Source.COST: "f.charge_date", Source.COMMITMENT: "f.charge_date"},
    "month": {
        Source.COST: "date_trunc('month', f.charge_date)",
        Source.COMMITMENT: "date_trunc('month', f.charge_date)",
    },
    "provider": {Source.COST: "s.provider_name", Source.COMMITMENT: "f.provider_name"},
    "service_category": {Source.COST: "s.service_category"},
    "service": {Source.COST: "s.service_name"},
    "region": {Source.COST: "r.region_id"},
    "team": {Source.COST: "a.team"},
    "environment": {Source.COST: "a.environment"},
    "charge_category": {Source.COST: "f.charge_category"},
    "dataset": {Source.COST: "f.source_dataset"},
}

_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class MetricError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Metric:
    name: str
    label: str
    source: Source
    kind: Kind
    numerator: str
    unit: str
    better: str
    owner: str
    description: str
    denominator: str | None = None

    def validate(self) -> None:
        if not _NAME.match(self.name):
            raise MetricError(f"{self.name!r}: names are lower_snake_case")
        if self.better not in {"higher", "lower", "neutral"}:
            raise MetricError(f"{self.name}: better must be higher, lower or neutral")
        allowed = COMPONENTS[self.source]
        if self.numerator not in allowed:
            raise MetricError(f"{self.name}: unknown numerator {self.numerator!r}")
        if self.kind is Kind.SUM:
            if self.denominator is not None:
                raise MetricError(f"{self.name}: a sum has no denominator")
        elif self.denominator not in allowed:
            raise MetricError(f"{self.name}: unknown denominator {self.denominator!r}")


def load(path: Path = SPEC_PATH) -> dict[str, Metric]:
    """Every metric in the spec, validated, keyed by name."""
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    metrics: dict[str, Metric] = {}
    for entry in raw["metrics"]:
        fields = dict(entry)
        fields["kind"] = Kind(fields["kind"])
        fields["source"] = Source(fields["source"])
        fields["description"] = " ".join(str(fields["description"]).split())
        metric = Metric(**fields)
        metric.validate()
        if metric.name in metrics:
            raise MetricError(f"duplicate metric {metric.name}")
        metrics[metric.name] = metric
    return metrics


def _relation(source: Source, schema: str) -> str:
    if source is Source.COMMITMENT:
        return f"{schema}.agg_commitment_daily as f"
    return (
        f"{schema}.fct_cost_daily as f"
        f" left join {schema}.dim_service as s using (service_key)"
        f" left join {schema}.dim_account as a using (account_key)"
        f" left join {schema}.dim_region as r using (region_key)"
    )


def _expression(dim: str, metric: Metric) -> str:
    try:
        return DIMENSIONS[dim][metric.source]
    except KeyError:
        raise MetricError(f"{metric.name} does not support the dimension {dim!r}") from None


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def value_sql(metric: Metric) -> str:
    """The aggregate expression for ``metric`` over the source aliased ``f``."""
    num = f"sum(f.{metric.numerator})"
    if metric.kind is Kind.SUM:
        return num
    ratio = f"cast({num} as double) / nullif(sum(f.{metric.denominator}), 0)"
    return ratio if metric.kind is Kind.RATIO else f"1 - {ratio}"


def sql(
    metric: Metric,
    *,
    group_by: Sequence[str] = (),
    where: Mapping[str, str] | None = None,
    schema: str = "marts",
) -> str:
    """SQL returning one row per group with the metric in a column named ``value``.

    ``where`` maps a dimension to one value; values are quoted, never interpolated raw.
    """
    columns = [f"{_expression(d, metric)} as {d}" for d in group_by]
    filters = [f"{_expression(d, metric)} = {_literal(v)}" for d, v in (where or {}).items()]
    query = f"select {', '.join([*columns, value_sql(metric) + ' as value'])}"
    query += f" from {_relation(metric.source, schema)}"
    if filters:
        query += " where " + " and ".join(filters)
    if group_by:
        keys = ", ".join(group_by)
        query += f" group by {keys} order by {keys}"
    return query


def dictionary(metrics: Mapping[str, Metric]) -> str:
    """The metric dictionary as Markdown, written to docs/metric_dictionary.md."""
    relation = {Source.COST: "fct_cost_daily", Source.COMMITMENT: "agg_commitment_daily"}
    lines = [
        "# Metric dictionary",
        "",
        "Every cost metric, its owner and exactly how it is computed. This page is written",
        "by `finops metrics` from `metrics/metrics.yml`; edit the YAML, not this file.",
        "",
        "| Metric | Definition | Computed as | Unit | Better | Owner |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for m in metrics.values():
        how = f"sum({m.numerator})"
        if m.kind is not Kind.SUM:
            how += f" / sum({m.denominator})"
        if m.kind is Kind.SAVINGS:
            how = f"1 - {how}"
        lines.append(
            f"| **{m.label}** (`{m.name}`) | {m.description} | {how} over"
            f" {relation[m.source]} | {m.unit} | {m.better} | {m.owner} |"
        )
    lines += ["", "Dimensions each source supports:", ""]
    for source in Source:
        dims = ", ".join(f"`{d}`" for d, exprs in DIMENSIONS.items() if source in exprs)
        lines.append(f"- {source.value} metrics: {dims}")
    lines.append("")
    return "\n".join(lines)
