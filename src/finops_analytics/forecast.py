"""Daily spend forecasts, judged by rolling-origin backtests.

The forecasters here are deliberately simple baselines. A model only earns a place when
it beats them on the same folds, so the baselines and the backtest come first.

A backtest never lets a forecast see its own future: the series is cut at an origin, the
forecaster sees only what came before, and the origin then rolls forward. Prediction
intervals come from the backtest's own errors at each horizon step (the empirical
quantiles of past residuals), and their coverage is checked on later folds that were not
used to size them.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.float64]
Forecaster = Callable[[Array, int], Array]

WEEK = 7


class ForecastError(ValueError):
    pass


def naive_last(history: Array, horizon: int) -> Array:
    """Tomorrow looks like today."""
    return np.full(horizon, history[-1])


def seasonal_naive(history: Array, horizon: int) -> Array:
    """Each day looks like the same weekday last week."""
    if len(history) < WEEK:
        raise ForecastError("seasonal_naive needs at least one week of history")
    last_week = history[-WEEK:]
    return last_week[np.arange(horizon) % WEEK]


def seasonal_drift(history: Array, horizon: int, weeks: int = 8) -> Array:
    """Last week's shape, moved by the average week-over-week change of recent weeks."""
    if len(history) < 2 * WEEK:
        raise ForecastError("seasonal_drift needs at least two weeks of history")
    weeks = min(weeks, len(history) // WEEK - 1)
    recent = history[-(weeks + 1) * WEEK :]
    weekly_totals = recent.reshape(weeks + 1, WEEK).sum(axis=1)
    daily_drift = float(np.diff(weekly_totals).mean()) / WEEK / WEEK
    steps = np.arange(1, horizon + 1)
    return seasonal_naive(history, horizon) + daily_drift * (WEEK * ((steps - 1) // WEEK + 1))


FORECASTERS: dict[str, Forecaster] = {
    "naive_last": naive_last,
    "seasonal_naive": seasonal_naive,
    "seasonal_drift": seasonal_drift,
}


@dataclass(frozen=True)
class Backtest:
    """Forecasts and actuals for every fold: arrays of shape (folds, horizon)."""

    origins: tuple[int, ...]
    forecast: Array
    actual: Array

    @property
    def errors(self) -> Array:
        return self.actual - self.forecast

    def wape(self) -> float:
        """Weighted absolute percentage error: total absolute error over total actual.

        Unlike a mean of per-day percentages it is not dominated by small days."""
        return float(np.abs(self.errors).sum()) / float(np.abs(self.actual).sum())

    def bias(self) -> float:
        """Total error over total actual; negative means the forecast runs high."""
        return float(self.errors.sum()) / float(np.abs(self.actual).sum())

    def wape_by_step(self) -> Array:
        total: Array = np.abs(self.actual).sum(axis=0)
        absolute: Array = np.abs(self.errors).sum(axis=0)
        return absolute / total


def rolling_origin(
    series: Sequence[float] | Array,
    forecaster: Forecaster,
    *,
    horizon: int,
    initial: int,
    step: int = WEEK,
) -> Backtest:
    """Forecast ``horizon`` days from each origin, moving the origin ``step`` days.

    The first origin is after ``initial`` days; a fold is only used when the full
    horizon of actuals exists, so every fold is scored on the same number of days.
    """
    values = np.asarray(series, dtype=np.float64)
    if horizon <= 0 or step <= 0 or initial <= 0:
        raise ForecastError("horizon, initial and step must be positive")
    origins = tuple(range(initial, len(values) - horizon + 1, step))
    if not origins:
        raise ForecastError("series too short for one fold")
    forecast = np.stack([forecaster(values[:o], horizon) for o in origins])
    actual = np.stack([values[o : o + horizon] for o in origins])
    return Backtest(origins, forecast, actual)


@dataclass(frozen=True)
class Intervals:
    """Residual quantiles per horizon step; add them to a forecast to get a band."""

    level: float
    lower: Array
    upper: Array

    def band(self, forecast: Array) -> tuple[Array, Array]:
        return forecast + self.lower, forecast + self.upper


def intervals(backtest: Backtest, level: float = 0.8) -> Intervals:
    """Empirical prediction intervals from a backtest's residuals at each step."""
    if not 0 < level < 1:
        raise ForecastError("level must be between 0 and 1")
    tail = (1 - level) / 2
    lower, upper = np.quantile(backtest.errors, [tail, 1 - tail], axis=0)
    return Intervals(level, lower, upper)


def coverage(backtest: Backtest, level: float = 0.8, calibration_share: float = 0.5) -> float:
    """Share of actuals inside the interval on folds the interval never saw.

    The earlier folds size the interval and the later ones test it, in time order, so
    the number is an out-of-sample check and not a restatement of the quantile.
    """
    folds = len(backtest.origins)
    split = int(folds * calibration_share)
    if split < 2 or folds - split < 1:
        raise ForecastError("not enough folds to calibrate and test intervals")
    calibrate = Backtest(
        backtest.origins[:split], backtest.forecast[:split], backtest.actual[:split]
    )
    band = intervals(calibrate, level)
    lower, upper = band.band(backtest.forecast[split:])
    actual = backtest.actual[split:]
    return float(((actual >= lower) & (actual <= upper)).mean())


@dataclass(frozen=True)
class Score:
    model: str
    folds: int
    wape: float
    bias: float
    coverage: float


def compare(
    series: Sequence[float] | Array,
    *,
    horizon: int = 28,
    initial: int = 365,
    step: int = WEEK,
    level: float = 0.8,
) -> list[Score]:
    """Every baseline on the same folds, best WAPE first."""
    scores = []
    for name, forecaster in FORECASTERS.items():
        result = rolling_origin(series, forecaster, horizon=horizon, initial=initial, step=step)
        scores.append(
            Score(name, len(result.origins), result.wape(), result.bias(), coverage(result, level))
        )
    return sorted(scores, key=lambda s: s.wape)
