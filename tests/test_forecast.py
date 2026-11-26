import datetime as dt
from pathlib import Path

import duckdb
import numpy as np
import pytest

from finops_analytics.cli import daily_spend, main
from finops_analytics.forecast import (
    Backtest,
    ForecastError,
    compare,
    coverage,
    intervals,
    naive_last,
    rolling_origin,
    seasonal_drift,
    seasonal_naive,
)

WEEKLY = np.array([10.0, 12, 11, 13, 12, 6, 5])


def _weekly(weeks: int, growth: float = 0.0) -> np.ndarray:
    return np.concatenate([WEEKLY + growth * w for w in range(weeks)])


def test_naive_last_repeats_the_final_value() -> None:
    assert naive_last(np.array([1.0, 2, 3]), 4).tolist() == [3, 3, 3, 3]


def test_seasonal_naive_repeats_last_week_by_weekday() -> None:
    forecast = seasonal_naive(_weekly(3), 9)
    assert forecast.tolist() == [*WEEKLY.tolist(), 10, 12]


def test_seasonal_drift_is_exact_on_a_steady_weekly_trend() -> None:
    history = _weekly(10, growth=7.0)
    future = np.concatenate([WEEKLY + 7.0 * w for w in range(10, 12)])
    assert seasonal_drift(history, 14) == pytest.approx(future)


def test_seasonal_drift_equals_seasonal_naive_without_a_trend() -> None:
    history = _weekly(6)
    assert seasonal_drift(history, 10) == pytest.approx(seasonal_naive(history, 10))


@pytest.mark.parametrize(("forecaster", "days"), [(seasonal_naive, 6), (seasonal_drift, 13)])
def test_forecasters_refuse_too_little_history(forecaster, days: int) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ForecastError):
        forecaster(np.ones(days), 7)


def test_rolling_origin_never_shows_a_forecaster_its_future() -> None:
    series = np.arange(100.0)
    seen: list[int] = []

    def spy(history: np.ndarray, horizon: int) -> np.ndarray:
        seen.append(len(history))
        assert history.max() == len(history) - 1
        return np.zeros(horizon)

    result = rolling_origin(series, spy, horizon=10, initial=50, step=20)
    assert result.origins == (50, 70, 90)
    assert seen == [50, 70, 90]
    assert result.actual[1].tolist() == list(range(70, 80))


def test_rolling_origin_drops_folds_without_a_full_horizon() -> None:
    result = rolling_origin(np.ones(60), naive_last, horizon=10, initial=50, step=7)
    assert result.origins == (50,)
    with pytest.raises(ForecastError, match="too short"):
        rolling_origin(np.ones(55), naive_last, horizon=10, initial=50)


def test_wape_and_bias_are_computed_on_totals() -> None:
    result = Backtest((0,), np.array([[10.0, 100.0]]), np.array([[5.0, 110.0]]))
    assert result.wape() == pytest.approx(15 / 115)
    assert result.bias() == pytest.approx(5 / 115)
    assert result.wape_by_step().tolist() == pytest.approx([1.0, 10 / 110])


def test_interval_width_is_a_corrected_quantile_of_absolute_errors() -> None:
    errors = np.arange(-5.0, 6.0).reshape(11, 1)  # absolute values 0, 1, 1, ... 5, 5
    band = intervals(errors, level=0.8)
    # rank ceil(12 * 0.8) = 10 of 11 absolute errors, which is 5
    assert band.width.tolist() == [5.0]
    lower, upper = band.band(np.array([100.0]))
    assert (lower[0], upper[0]) == (95.0, 105.0)


def test_intervals_widen_with_fewer_past_errors() -> None:
    rng = np.random.default_rng(5)
    errors = rng.normal(0, 1, (400, 1))
    assert intervals(errors[:10]).width[0] >= np.quantile(np.abs(errors[:10]), 0.8)
    assert intervals(errors).width[0] == pytest.approx(1.28, abs=0.1)
    with pytest.raises(ForecastError, match="no past errors"):
        intervals(errors[:0])
    with pytest.raises(ForecastError, match="between 0 and 1"):
        intervals(errors, level=1.0)


def test_coverage_matches_the_level_when_errors_are_stable() -> None:
    rng = np.random.default_rng(3)
    series = 100 + rng.normal(0, 5, 4000)
    result = rolling_origin(series, lambda _, h: np.full(h, 100.0), horizon=7, initial=100, step=7)
    assert coverage(result, level=0.8) == pytest.approx(0.8, abs=0.02)


def test_coverage_only_uses_errors_known_at_each_origin() -> None:
    # Errors are zero until the last fold, whose error is large. If that fold's own error
    # (or any not yet observed) sized its interval, it would be covered; it must not be.
    forecast = np.zeros((30, 7))
    actual = np.zeros((30, 7))
    actual[-1] = 50.0
    result = Backtest(tuple(range(0, 210, 7)), forecast, actual)
    scored = 30 - 20  # folds with at least 20 fully observed predecessors
    assert coverage(result) == pytest.approx((scored - 1) / scored)


def test_coverage_drops_when_errors_grow() -> None:
    rng = np.random.default_rng(9)
    noise = rng.normal(0, 1, 2000) * np.linspace(1, 6, 2000)
    result = rolling_origin(100 + noise, lambda _, h: np.full(h, 100.0), horizon=7, initial=100)
    assert coverage(result, level=0.8) < 0.75


def test_coverage_needs_enough_folds() -> None:
    result = rolling_origin(np.ones(120), naive_last, horizon=7, initial=50, step=7)
    with pytest.raises(ForecastError, match="folds"):
        coverage(result)


def test_compare_ranks_the_seasonal_models_first_on_weekly_data() -> None:
    rng = np.random.default_rng(11)
    series = _weekly(110, growth=0.5) + rng.normal(0, 0.4, 770)
    scores = compare(series, horizon=28, initial=365)
    assert [s.model for s in scores][-1] == "naive_last"
    assert all(s.coverage is not None and 0.7 < s.coverage <= 1 for s in scores)
    assert scores[0].model == "seasonal_drift"
    assert len({s.folds for s in scores}) == 1


@pytest.fixture
def warehouse(tmp_path: Path) -> Path:
    path = tmp_path / "wh.duckdb"
    start = dt.date(2025, 1, 1)
    rows = []
    for day, value in enumerate(_weekly(70, growth=0.2)):
        date = start + dt.timedelta(days=day)
        rows += [(date, "compute", True, value), (date, "storage", True, 1.0)]
    rows.append((start, "compute", False, 999.0))  # real sample data is left out
    with duckdb.connect(str(path)) as con:
        con.execute("create schema marts")
        con.execute(
            "create table marts.fct_cost_daily (charge_date date, service_key varchar, "
            "is_synthetic boolean, effective_cost decimal(38, 9))"
        )
        con.executemany("insert into marts.fct_cost_daily values (?, ?, ?, ?)", rows)
        con.execute(
            "create table marts.dim_service as select * from "
            "(values ('compute', 'Compute'), ('storage', 'Storage')) t(service_key, service_name)"
        )
    return path


def test_daily_spend_sums_services_and_skips_non_synthetic_rows(warehouse: Path) -> None:
    total = daily_spend(warehouse, None)
    compute = daily_spend(warehouse, "Compute")
    assert len(total) == len(compute) == 490
    assert total[0] == pytest.approx(compute[0] + 1.0) and compute[0] == pytest.approx(10.0)


def test_forecast_command_prints_one_row_per_model(
    warehouse: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["forecast", "--warehouse", str(warehouse), "--service", "Compute"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "490 days, 14 folds, horizon 28 days"
    assert [line.split()[0] for line in lines[2:]] == [
        "seasonal_drift",
        "seasonal_naive",
        "naive_last",
    ]
    # Fourteen folds cannot size an interval and test it; the command says so.
    assert all(line.endswith("too few folds") for line in lines[2:])


def test_forecast_command_explains_what_it_cannot_do(
    warehouse: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["forecast", "--warehouse", str(warehouse), "--service", "Nope"]) == 2
    assert main(["forecast", "--warehouse", str(warehouse), "--initial", "480"]) == 2
    out = capsys.readouterr().out
    assert "no synthetic spend" in out and "cannot backtest" in out
