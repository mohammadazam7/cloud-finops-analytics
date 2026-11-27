import datetime as dt

import pyarrow as pa
import pytest

from finops_analytics.attribution import explain, format_explanation
from finops_analytics.synthetic import generate

START = dt.date(2025, 3, 1)


def day(offset: int) -> dt.date:
    return START + dt.timedelta(days=offset)


def charges(rows: list[tuple[int, str, str, str, float]], **extra: list[object]) -> pa.Table:
    """Rows of (day offset, account, service, region, cost) as FOCUS usage charges."""
    n = len(rows)
    columns: dict[str, list[object]] = {
        "ChargePeriodStart": [dt.datetime.combine(day(r[0]), dt.time()) for r in rows],
        "SubAccountId": [r[1] for r in rows],
        "ServiceName": [r[2] for r in rows],
        "RegionId": [r[3] for r in rows],
        "SkuId": [f"{r[2]}-{r[3]}" for r in rows],
        "ServiceCategory": ["Compute"] * n,
        "ProviderName": ["AWS"] * n,
        "EffectiveCost": [r[4] for r in rows],
        "ChargeCategory": ["Usage"] * n,
        "CommitmentDiscountStatus": [None] * n,
    }
    columns.update(extra)
    return pa.table(columns)


def steady(days: int = 10) -> list[tuple[int, str, str, str, float]]:
    """Ten quiet days: compute 100 a day and storage 40 a day in one account, and
    compute 60 a day in another."""
    rows = []
    for d in range(days):
        rows += [
            (d, "prod", "compute", "us-east-1", 100.0),
            (d, "prod", "storage", "us-east-1", 40.0),
            (d, "dev", "compute", "eu-west-1", 60.0),
        ]
    return rows


def test_a_spike_in_one_service_is_the_whole_change() -> None:
    rows = [*steady(), (10, "prod", "compute", "us-east-1", 400.0)]
    rows += [(10, "prod", "storage", "us-east-1", 40.0), (10, "dev", "compute", "eu-west-1", 60.0)]
    result = explain(charges(rows), day(10), day(10), by=["account", "service"])
    assert (result.expected, result.actual, result.change) == (200.0, 500.0, 300.0)
    assert result.baseline_days == 10
    top = result.drivers[0]
    assert top.key == ("prod", "compute")
    assert (top.expected, top.actual, top.change) == (100.0, 400.0, 300.0)
    assert result.share(top) == 1.0
    assert [d.change for d in result.drivers[1:]] == [0.0, 0.0]


def test_the_parts_always_sum_to_the_total() -> None:
    billing = generate()
    first, last = dt.date(2025, 6, 10), dt.date(2025, 6, 16)
    for by in (["service"], ["account"], ["region"], ["account", "service", "region"]):
        full = explain(billing.charges, first, last, by=by, top=None)
        assert sum(d.change for d in full.drivers) == pytest.approx(full.change, abs=1e-6)
        assert full.others == 0 and full.others_change == 0
        short = explain(billing.charges, first, last, by=by, top=2)
        listed = sum(d.change for d in short.drivers)
        assert listed + short.others_change == pytest.approx(full.change, abs=1e-6)
        # The total does not depend on how it is split.
        assert full.change == pytest.approx(
            explain(billing.charges, first, last, by=["provider"], top=None).change, abs=1e-6
        )


def test_a_longer_period_is_compared_with_as_many_expected_days() -> None:
    rows = steady()
    for d in (10, 11, 12):
        rows += [
            (d, "prod", "compute", "us-east-1", 150.0),
            (d, "prod", "storage", "us-east-1", 40.0),
            (d, "dev", "compute", "eu-west-1", 60.0),
        ]
    result = explain(charges(rows), day(10), day(12), by=["service"])
    assert result.expected == pytest.approx(600.0)
    assert result.change == pytest.approx(150.0)
    assert result.drivers[0].key == ("compute",)
    assert result.share(result.drivers[0]) == pytest.approx(1.0)


def test_a_new_service_and_one_that_stopped_are_both_explained() -> None:
    rows = [*steady(), (10, "prod", "compute", "us-east-1", 100.0)]
    rows += [(10, "dev", "compute", "eu-west-1", 60.0), (10, "prod", "search", "us-east-1", 90.0)]
    result = explain(charges(rows), day(10), day(10), by=["service"], top=None)
    by_key = {d.key[0]: d for d in result.drivers}
    assert (by_key["search"].expected, by_key["search"].change) == (0.0, 90.0)
    assert (by_key["storage"].actual, by_key["storage"].change) == (0.0, -40.0)
    assert result.change == 50.0
    # search explains more than the whole rise because storage fell at the same time
    assert result.share(by_key["search"]) == pytest.approx(1.8)
    assert result.share(by_key["storage"]) == pytest.approx(-0.8)
    # largest movement first, whichever way it went
    assert [d.key[0] for d in result.drivers] == ["search", "storage", "compute"]


def test_a_fall_and_a_smaller_rise_are_listed_by_size() -> None:
    rows = [*steady(), (10, "prod", "compute", "us-east-1", 20.0)]
    rows += [(10, "prod", "storage", "us-east-1", 45.0), (10, "dev", "compute", "eu-west-1", 60.0)]
    result = explain(charges(rows), day(10), day(10), by=["account", "service"])
    assert result.change == -75.0
    assert [(d.key, d.change) for d in result.drivers] == [
        (("prod", "compute"), -80.0),
        (("prod", "storage"), 5.0),
        (("dev", "compute"), 0.0),
    ]
    assert result.share(result.drivers[0]) == pytest.approx(80 / 75)


def test_where_narrows_the_question_to_one_account() -> None:
    rows = [*steady(), (10, "prod", "compute", "us-east-1", 100.0)]
    rows += [(10, "prod", "storage", "us-east-1", 70.0), (10, "dev", "compute", "eu-west-1", 500.0)]
    result = explain(charges(rows), day(10), day(10), by=["service"], where={"account": "prod"})
    assert (result.expected, result.actual) == (140.0, 170.0)
    assert result.drivers[0].key == ("storage",)


def test_purchases_and_unused_commitment_are_left_out() -> None:
    rows = [*steady(), (10, "prod", "compute", "us-east-1", 100.0)]
    rows += [(10, "prod", "fee", "us-east-1", 5000.0), (10, "prod", "plan", "us-east-1", 300.0)]
    table = charges(rows)
    category = ["Usage"] * (len(rows) - 2) + ["Purchase", "Usage"]
    status = [None] * (len(rows) - 1) + ["Unused"]
    table = table.set_column(
        table.schema.get_field_index("ChargeCategory"), "ChargeCategory", [category]
    )
    table = table.set_column(
        table.schema.get_field_index("CommitmentDiscountStatus"),
        "CommitmentDiscountStatus",
        pa.array(status, type=pa.string()),
    )
    result = explain(table, day(10), day(10), by=["service"], top=None)
    assert {d.key[0] for d in result.drivers} == {"compute", "storage"}
    assert result.actual == 100.0


def test_missing_days_in_the_baseline_are_not_counted_as_zero_spend() -> None:
    rows = [r for r in steady() if r[0] not in (3, 4, 5)]
    rows.append((10, "prod", "compute", "us-east-1", 100.0))
    result = explain(charges(rows), day(10), day(10), by=["account"], where={"service": "compute"})
    assert result.baseline_days == 7
    assert {d.key[0]: d.expected for d in result.drivers} == {"dev": 60.0, "prod": 100.0}


def test_the_window_limits_how_far_back_the_expectation_looks() -> None:
    rows = [(d, "prod", "compute", "us-east-1", 10.0 if d < 5 else 100.0) for d in range(10)]
    rows.append((10, "prod", "compute", "us-east-1", 100.0))
    assert explain(charges(rows), day(10), day(10), window=5).change == 0.0
    plain = explain(charges(rows), day(10), day(10), window=10, seasonal=False)
    assert plain.change == pytest.approx(45.0)  # against the mean of all ten days, 55


def test_a_weekly_rhythm_is_not_mistaken_for_a_change() -> None:
    # Four weeks where weekends cost a fifth of weekdays, then an ordinary Saturday.
    rows = [
        (d, "prod", "compute", "us-east-1", 20.0 if day(d).weekday() >= 5 else 100.0)
        for d in range(29)
    ]
    saturday = next(d for d in range(28, 21, -1) if day(d).weekday() == 5)
    table = charges([r for r in rows if r[0] <= saturday])
    assert explain(table, day(saturday), day(saturday)).change == pytest.approx(0.0)
    plain = explain(table, day(saturday), day(saturday), seasonal=False)
    assert plain.change < -50  # the plain average calls every Saturday a fall


def test_a_weekday_missing_from_a_short_baseline_falls_back_to_the_plain_mean() -> None:
    rows = [(d, "prod", "compute", "us-east-1", 100.0) for d in range(3)]
    rows.append((3, "prod", "compute", "us-east-1", 130.0))
    result = explain(charges(rows), day(3), day(3))
    assert (result.baseline_days, result.expected, result.change) == (3, 100.0, 30.0)


def _ranks(seasonal: bool) -> list[tuple[int, float]]:
    """For each planted anomaly: where its series ranks among the drivers of total spend
    over its own days, and how many dollars it moved."""
    billing = generate()
    out = []
    for row in billing.anomalies.to_pylist():
        result = explain(
            billing.charges,
            row["first_day"],
            row["last_day"],
            by=["account", "service", "region"],
            top=None,
            seasonal=seasonal,
        )
        key = (row["SubAccountId"], row["ServiceName"], row["RegionId"])
        position = [d.key for d in result.drivers].index(key)
        out.append((position + 1, result.drivers[position].change))
    return out


def test_large_planted_anomalies_lead_the_explanation_and_small_ones_do_not() -> None:
    ranks = _ranks(seasonal=True)
    assert len(ranks) == 18
    large = [rank for rank, change in ranks if change >= 100]
    small = [rank for rank, change in ranks if change < 30]
    # Every planted anomaly worth 100 USD or more is first or second; the two in second
    # place sit behind a larger fall somewhere else on the same days.
    assert len(large) == 11 and sorted(large) == [1] * 9 + [2] * 2
    # The ones worth under 30 USD are buried under ordinary movement of large services.
    # Finding those is the detector's job, series by series, not attribution's.
    assert len(small) == 6 and min(small) >= 6
    assert sum(rank == 1 for rank, _ in ranks) == 10


def test_the_same_weekday_baseline_ranks_planted_anomalies_higher_than_a_plain_mean() -> None:
    seasonal = [rank for rank, _ in _ranks(seasonal=True)]
    plain = [rank for rank, _ in _ranks(seasonal=False)]
    assert sum(r == 1 for r in plain) == 8
    assert sum(seasonal) < sum(plain)
    assert all(a <= b for a, b in zip(seasonal, plain, strict=True))


def test_the_text_form_reads_total_first_then_drivers() -> None:
    rows = [*steady(), (10, "prod", "compute", "us-east-1", 400.0)]
    rows += [(10, "prod", "storage", "us-east-1", 40.0), (10, "dev", "compute", "eu-west-1", 60.0)]
    text = format_explanation(
        explain(charges(rows), day(10), day(10), by=["account", "service"], top=1)
    )
    lines = text.splitlines()
    assert (
        lines[0] == "2025-03-11: 500.00 against 200.00 expected (+300.00), by account and service"
    )
    assert lines[1].split() == ["prod", "/", "compute", "+300.00", "100.0%", "of", "the", "change"]
    assert lines[2].split() == ["2", "others", "+0.00"]
    quiet = format_explanation(explain(charges(steady(11)), day(8), day(10), by=["service"]))
    assert quiet.startswith("2025-03-09 to 2025-03-11:") and "of the change" not in quiet


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"by": ["team"]}, "unknown dimension 'team'"),
        ({"by": []}, "at least one dimension"),
        ({"where": {"owner": "x"}}, "unknown dimension 'owner'"),
        ({"window": 0}, "at least one day"),
        ({"top": 0}, "top must be at least 1"),
    ],
)
def test_bad_questions_are_refused(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        explain(charges(steady(11)), day(10), day(10), **kwargs)  # type: ignore[arg-type]


def test_a_period_needs_days_before_it_and_an_end_after_its_start() -> None:
    table = charges(steady(11))
    with pytest.raises(ValueError, match="ends before it starts"):
        explain(table, day(5), day(4))
    with pytest.raises(ValueError, match="nothing to compare with"):
        explain(table, day(0), day(2))
