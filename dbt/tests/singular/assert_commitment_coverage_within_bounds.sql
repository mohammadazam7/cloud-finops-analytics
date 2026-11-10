-- Covered usage is part of eligible usage, so coverage can never exceed 1 on any day.
select charge_date, provider_name, covered_list_cost, eligible_list_cost
from {{ ref('agg_commitment_daily') }}
where covered_list_cost > eligible_list_cost + 0.000001
