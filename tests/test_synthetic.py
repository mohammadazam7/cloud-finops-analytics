import datetime as dt

import pyarrow as pa
import pyarrow.compute as pc
import pytest

from finops_analytics.focus import check
from finops_analytics.synthetic import SAVINGS_PLAN_DISCOUNT, SyntheticConfig, generate

# 123 days from Oct 1 ends on Jan 31, so every billing month in the window is complete.
SMALL = SyntheticConfig(seed=5, days=123, teams=2, anomalies=4, migrations=1)


@pytest.fixture(scope="module")
def billing():  # type: ignore[no-untyped-def]
    return generate(SMALL)


def _as_text(table: pa.Table) -> pa.Table:
    """The table as a FOCUS CSV export would load: every column text."""
    cols = {}
    for name in table.column_names:
        col = table.column(name)
        if pa.types.is_timestamp(col.type):
            col = pc.strftime(col, "%Y-%m-%d %H:%M:%S")
        cols[name] = pc.cast(col, pa.string())
    return pa.table(cols)


def test_same_seed_same_output(billing) -> None:  # type: ignore[no-untyped-def]
    again = generate(SMALL)
    assert billing.charges.equals(again.charges)
    assert billing.anomalies.equals(again.anomalies)


def test_output_conforms_to_focus(billing) -> None:  # type: ignore[no-untyped-def]
    assert check(_as_text(billing.charges)) == []


def test_every_row_is_labelled_synthetic(billing) -> None:  # type: ignore[no-untyped-def]
    assert pc.all(billing.charges.column("x_Synthetic")).as_py()


def test_amortized_cost_reconciles_to_the_invoice(billing) -> None:  # type: ignore[no-untyped-def]
    # Commitment fees are billed up front and amortized into usage, so over complete
    # months the amortized (effective) cost and the invoiced (billed) cost must agree.
    c = billing.charges
    billed = pc.sum(c.column("BilledCost")).as_py()
    effective = pc.sum(c.column("EffectiveCost")).as_py()
    assert effective == pytest.approx(billed, rel=1e-9)


def test_committed_usage_is_discounted(billing) -> None:  # type: ignore[no-untyped-def]
    c = billing.charges
    used = c.filter(pc.equal(c.column("CommitmentDiscountStatus"), "Used"))
    ratio = pc.sum(used.column("EffectiveCost")).as_py() / pc.sum(used.column("ListCost")).as_py()
    assert ratio == pytest.approx(1 - SAVINGS_PLAN_DISCOUNT)


def test_anomalies_are_recorded_inside_the_window(billing) -> None:  # type: ignore[no-untyped-def]
    a = billing.anomalies
    assert a.num_rows == SMALL.anomalies
    end = SMALL.start + dt.timedelta(days=SMALL.days - 1)
    for row in a.to_pylist():
        assert SMALL.start <= row["first_day"] <= row["last_day"] <= end
        assert row["factor"] > 1


def test_spend_grows(billing) -> None:  # type: ignore[no-untyped-def]
    c = billing.charges.filter(pc.equal(billing.charges.column("ChargeCategory"), "Usage"))
    day = pc.cast(c.column("ChargePeriodStart"), pa.date32())
    first = pc.sum(
        pc.filter(
            c.column("EffectiveCost"), pc.less(day, pa.scalar(SMALL.start + dt.timedelta(days=28)))
        )
    )
    last = pc.sum(
        pc.filter(
            c.column("EffectiveCost"),
            pc.greater_equal(day, pa.scalar(SMALL.start + dt.timedelta(days=SMALL.days - 28))),
        )
    )
    assert last.as_py() > first.as_py()


@pytest.mark.parametrize(
    "kwargs", [{"days": 30}, {"teams": 0}, {"teams": 99}, {"plan_coverage": 1.5}]
)
def test_invalid_config(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        SyntheticConfig(**kwargs)  # type: ignore[arg-type]
