-- Commitment use and coverage per day and provider, in additive parts.
--
-- fct_commitment_utilization repeats a provider's eligible list cost on every commitment
-- row for that day, so summing it across commitments counts it more than once. This model
-- holds one row per day and provider, where every column can be summed over any period
-- and coverage is sum(covered_list_cost) / sum(eligible_list_cost).
--
-- A day whose eligible list cost is not positive (credits can outweigh usage; the FOCUS
-- sample has one such Microsoft day) has no meaningful coverage, so both coverage parts
-- are zero for it and it drops out of any rollup instead of distorting it.
select
    charge_date,
    provider_name,
    sum(used_cost) as used_cost,
    sum(unused_cost) as unused_cost,
    sum(used_cost) + sum(unused_cost) as committed_cost,
    case when max(eligible_list_cost) > 0 then sum(covered_list_cost) else 0 end
        as covered_list_cost,
    greatest(max(eligible_list_cost), 0) as eligible_list_cost
from {{ ref('fct_commitment_utilization') }}
group by charge_date, provider_name
