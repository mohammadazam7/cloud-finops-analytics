"""Daily spend forecasts, judged by rolling-origin backtests.

The forecasters here are deliberately simple baselines. A model only earns a place when
it beats them on the same folds, so the baselines and the backtest come first.

A backtest never lets a forecast see its own future: the series is cut at an origin, the
forecaster sees only what came before, and the origin then rolls forward. Prediction
intervals are split-conformal: a quantile of past absolute errors at each step ahead,
with a correction for the sample being finite. Their coverage is measured the way they
would be used, each interval sized only from errors already known at its origin.
"""

from __future__ import annotations

import math
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
    """How far actuals may fall from a forecast at each step ahead, at a given level."""

    level: float
    width: Array

    def band(self, forecast: Array) -> tuple[Array, Array]:
        return forecast - self.width, forecast + self.width


def intervals(errors: Array, level: float = 0.8) -> Intervals:
    """Split-conformal prediction intervals from past forecast errors.

    ``errors`` has one row per past forecast and one column per step ahead. The width at
    each step is a quantile of the absolute errors, taken slightly above ``level`` to
    allow for the errors being a finite sample: rank ``ceil((n + 1) * level)`` of ``n``.
    Plain empirical quantiles skip that correction and come out too narrow on few folds.
    """
    if not 0 < level < 1:
        raise ForecastError("level must be between 0 and 1")
    n = len(errors)
    if n == 0:
        raise ForecastError("no past errors to size an interval from")
    rank = min(1.0, math.ceil((n + 1) * level) / n)
    width: Array = np.quantile(np.abs(errors), rank, axis=0, method="higher")
    return Intervals(level, width)


def coverage(backtest: Backtest, level: float = 0.8, min_calibration: int = 20) -> float:
    """Share of actuals inside their interval, each interval sized as it would be live.

    For every fold, the interval uses only earlier folds whose whole horizon had already
    happened by that fold's origin: errors that were not yet known cannot size it. Folds
    with fewer than ``min_calibration`` such predecessors are not scored.
    """
    horizon = backtest.actual.shape[1]
    errors = backtest.errors
    inside = []
    for i, origin in enumerate(backtest.origins):
        known = [j for j in range(i) if backtest.origins[j] + horizon <= origin]
        if len(known) < min_calibration:
            continue
        lower, upper = intervals(errors[known], level).band(backtest.forecast[i])
        inside.append((backtest.actual[i] >= lower) & (backtest.actual[i] <= upper))
    if not inside:
        raise ForecastError("not enough folds to calibrate and test intervals")
    return float(np.mean(inside))


@dataclass(frozen=True)
class Score:
    model: str
    folds: int
    wape: float
    bias: float
    # None when the backtest has too few folds to size and test intervals.
    coverage: float | None


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
        try:
            covered: float | None = coverage(result, level)
        except ForecastError:
            covered = None
        scores.append(Score(name, len(result.origins), result.wape(), result.bias(), covered))
    return sorted(scores, key=lambda s: s.wape)
