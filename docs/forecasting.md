# Forecasting daily spend

Status: baselines and the backtest are in place; richer models come next and have to beat
the numbers below on the same folds to be kept.

## Method

- **Rolling origin.** The series is cut at an origin, a forecaster sees only the days
  before it and predicts the next 28, then the origin moves forward a week. The first
  origin comes after 365 days so every forecaster has a full year behind it.
- **WAPE** (total absolute error over total actual spend) is the headline error. A mean
  of daily percentage errors would let small days dominate.
- **Bias** is total error over total spend; negative means the forecast ran high.
- **Prediction intervals** are split-conformal: at each step ahead, the width is a
  quantile of past absolute errors, taken at rank `ceil((n + 1) * level)` of `n` to
  allow for the sample being finite.
- **Coverage** is measured the way the intervals would be used. Each fold's interval is
  sized only from earlier folds whose whole 28 days had already happened at that fold's
  origin, and a fold is scored once at least 20 such folds exist.

## Baselines

| Model | What it predicts |
|---|---|
| `naive_last` | Every future day equals the last observed day |
| `seasonal_naive` | Each day equals the same weekday of the last week |
| `seasonal_drift` | Last week's shape, moved by the average week-over-week change of the last eight weeks |

## Results on the synthetic history

All services together, 730 days of **synthetic** spend (seed 7), 49 folds, 28 days ahead.
Reproduce with `finops forecast --warehouse data/warehouse.duckdb`.

| Model | WAPE | Bias | Coverage of the 80% interval |
|---|---|---|---|
| `seasonal_drift` | 2.0% | -0.0% | 83.5% |
| `seasonal_naive` | 2.1% | +0.9% | 82.0% |
| `naive_last` | 8.4% | -6.1% | 75.3% |

WAPE and bias are over all 49 folds; coverage is over the last 26, the ones with enough
earlier folds to size an interval.

What this says:

- The weekly pattern is most of the signal. Ignoring it costs four times the error.
- Adding the recent trend removes the bias (`seasonal_naive` runs about 1% low on a
  growing bill) but barely moves WAPE.
- The intervals for the two seasonal models cover a little more than the 80% asked for,
  which is the side a conformal interval is meant to err on.
- `naive_last` still under-covers at 75.3%. Its absolute errors are about 8% larger in
  the 26 scored folds than in the 23 before them (2% for `seasonal_drift`), so past
  errors understate the next ones. That explains part of the gap; the rest has not been
  tracked down. An interval built from past errors cannot repair a forecast whose
  errors keep growing.

An earlier version of this page reported about 75% coverage for the seasonal models. Two
things were wrong with how that was measured, not with the forecasts: the quantiles had
no finite-sample correction, and the folds were split into halves, so the intervals
were sized on only 24 folds. Planted cost spikes were checked and ruled out as the
cause at the time (coverage was 74.9% on days without one and 70.8% on days with one).

These numbers describe generated data with a known weekly cycle and growth rate, so they
show the method works, not how well real bills can be forecast.
