-- The daily fact must carry every dollar of the staged billing lines, per source.
with f as (
    select source_dataset, sum(billed_cost) as billed, sum(effective_cost) as effective
    from {{ ref('fct_cost_daily') }}
    group by source_dataset
),
s as (
    select source_dataset, sum(billed_cost) as billed, sum(effective_cost) as effective
    from {{ ref('stg_billing_charges') }}
    group by source_dataset
)
select s.source_dataset, s.billed, f.billed as fact_billed, s.effective, f.effective as fact_effective
from s
left join f on s.source_dataset = f.source_dataset
where f.source_dataset is null
   or abs(s.billed - f.billed) > 0.01
   or abs(s.effective - f.effective) > 0.01
