-- One row per billing account and sub-account. Synthetic sub-accounts are named
-- team-environment, which gives the team and environment used for allocation.
select
    account_key,
    billing_account_id,
    any_value(billing_account_name) as billing_account_name,
    coalesce(sub_account_id, billing_account_id) as sub_account_id,
    any_value(sub_account_name) as sub_account_name,
    case when bool_or(is_synthetic) then split_part(any_value(sub_account_name), '-', 1) end as team,
    case when bool_or(is_synthetic) then split_part(any_value(sub_account_name), '-', 2) end as environment,
    bool_or(is_synthetic) as is_synthetic
from {{ ref('int_charges_keyed') }}
group by account_key, billing_account_id, coalesce(sub_account_id, billing_account_id)
