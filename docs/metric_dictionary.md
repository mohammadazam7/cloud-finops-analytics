# Metric dictionary

Every cost metric, its owner and exactly how it is computed. This page is written
by `finops metrics` from `metrics/metrics.yml`; edit the YAML, not this file.

| Metric | Definition | Computed as | Unit | Better | Owner |
| --- | --- | --- | --- | --- | --- |
| **Effective cost** (`effective_cost`) | Amortized cost after negotiated discounts, with commitment purchases spread over the days they cover. The basis for showback and chargeback. | sum(effective_cost) over fct_cost_daily | USD | lower | FinOps |
| **Billed cost** (`billed_cost`) | Cost as it appears on the invoice, with commitment purchases charged when bought. Used to reconcile against invoices, not to compare teams. | sum(billed_cost) over fct_cost_daily | USD | lower | Finance |
| **List cost** (`list_cost`) | Cost at public list prices before any discount or commitment. | sum(list_cost) over fct_cost_daily | USD | neutral | FinOps |
| **Effective savings rate** (`effective_savings_rate`) | Share of list cost avoided through negotiated discounts and commitments, across all spend. | 1 - sum(effective_cost) / sum(list_cost) over fct_cost_daily | share | higher | FinOps |
| **Commitment utilization** (`commitment_utilization`) | Share of committed spend (savings plans and reservations) that covered usage rather than going unused. | sum(used_cost) / sum(committed_cost) over agg_commitment_daily | share | higher | FinOps |
| **Unused commitment cost** (`unused_commitment_cost`) | Committed spend that no usage consumed. | sum(unused_cost) over agg_commitment_daily | USD | lower | FinOps |
| **Commitment coverage** (`commitment_coverage`) | Share of eligible compute usage, at list price, that ran under a commitment. Days whose eligible list cost is not positive are left out. | sum(covered_list_cost) / sum(eligible_list_cost) over agg_commitment_daily | share | higher | FinOps |

Dimensions each source supports:

- cost metrics: `date`, `month`, `provider`, `service_category`, `service`, `region`, `team`, `environment`, `charge_category`, `dataset`
- commitment metrics: `date`, `month`, `provider`
