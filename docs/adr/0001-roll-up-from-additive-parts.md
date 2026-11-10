# 0001. Roll ratio metrics up from additive parts

**Status:** Accepted

## Context

Utilization, coverage and savings rate are ratios. An average of daily ratios is not the
ratio for the period: a day with little committed spend counts as much as a day with a
lot. Coverage has a second trap. Its denominator, eligible usage, belongs to a day and
provider, but `fct_commitment_utilization` is at the commitment grain and repeats it on
every commitment row, so a sum across the four AWS savings plans counted it four times.

## Decision

Marts store the numerator and denominator of every ratio as additive columns, and the
metric layer always computes `sum(numerator) / sum(denominator)` at the requested grain.
Commitment metrics read `agg_commitment_daily`, one row per day and provider, where
every column can be summed. Days whose eligible list cost is not positive (credits can
outweigh usage) contribute zero to both coverage parts.

## Consequences

- Any period, provider or mix of the two gives the same answer a direct calculation
  would, and a test pins this with two days whose average differs from the true ratio.
- Coverage cannot be split by team or service: eligible usage is only known per day and
  provider. The metric layer rejects those groupings instead of returning wrong numbers.
