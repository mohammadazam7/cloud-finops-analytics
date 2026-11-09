-- Billing lines with the keys every mart joins on. Missing regions become 'global' (the
-- FOCUS sample leaves RegionId empty for global services) and a missing sub-account falls
-- back to the billing account, so no line drops out of a join.
select
    {{ dbt.hash("provider_name || '|' || service_name") }} as service_key,
    {{ dbt.hash("provider_name || '|' || coalesce(region_id, 'global')") }} as region_key,
    {{ dbt.hash("billing_account_id || '|' || coalesce(sub_account_id, billing_account_id)") }} as account_key,
    cast(charge_period_start as date) as charge_date,
    *
from {{ ref('stg_billing_charges') }}
