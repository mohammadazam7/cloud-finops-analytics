-- Daily use of each commitment (a savings plan or reservation) and how much of the
-- eligible usage it covered.
--
-- Utilization: the share of what the commitment cost that day that was used, from the
-- Used and Unused amortized lines. Coverage: the share of eligible compute usage, at list
-- price, that ran under a commitment. Both are stored as their additive parts as well, so
-- they can be rolled up correctly over any period.
with charges as (

    select * from {{ ref('int_charges_keyed') }}

),

commitments as (

    select
        charge_date,
        provider_name,
        commitment_discount_id,
        sum(case when commitment_discount_status = 'Used' then effective_cost else 0 end) as used_cost,
        sum(case when commitment_discount_status = 'Unused' then effective_cost else 0 end) as unused_cost,
        sum(case when commitment_discount_status = 'Used' then list_cost else 0 end) as covered_list_cost
    from charges
    where commitment_discount_id is not null and charge_category = 'Usage'
    group by charge_date, provider_name, commitment_discount_id

),

eligible as (

    select charge_date, provider_name, sum(list_cost) as eligible_list_cost
    from charges
    where charge_category = 'Usage'
        and service_category = 'Compute'
        and commitment_discount_status is distinct from 'Unused'
    group by charge_date, provider_name

)

select
    c.charge_date,
    c.provider_name,
    c.commitment_discount_id,
    c.used_cost,
    c.unused_cost,
    c.covered_list_cost,
    e.eligible_list_cost,
    c.used_cost / nullif(c.used_cost + c.unused_cost, 0) as utilization,
    case
        when e.eligible_list_cost > 0 then c.covered_list_cost / e.eligible_list_cost
    end as coverage
from commitments as c
left join eligible as e
    on c.charge_date = e.charge_date
    and c.provider_name = e.provider_name
