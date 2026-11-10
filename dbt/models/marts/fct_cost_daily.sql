{{
    config(
        materialized='incremental',
        unique_key=['charge_date', 'account_key', 'service_key', 'region_key', 'charge_category', 'source_dataset'],
        incremental_strategy=('merge' if target.type == 'bigquery' else 'delete+insert'),
        on_schema_change='fail',
        partition_by=(
            {'field': 'charge_date', 'data_type': 'date', 'granularity': 'day'}
            if target.type == 'bigquery' else none
        ),
        cluster_by=(['service_key', 'account_key'] if target.type == 'bigquery' else none),
    )
}}

-- Daily cost by account, service, region and charge category. Billed cost is what the
-- invoice says; effective cost spreads commitment purchases over the usage they cover, so
-- it is the number to allocate and trend. Each run reloads a lookback window before the
-- latest loaded day so late billing adjustments are picked up; the unique key makes the
-- reload idempotent. Amounts are NUMERIC(38, 9), exact on both DuckDB and BigQuery, so
-- sums of many small charges do not drift.
select
    charge_date,
    account_key,
    service_key,
    region_key,
    charge_category,
    source_dataset,
    bool_or(is_synthetic) as is_synthetic,
    cast(count(*) as int64) as line_count,
    cast(sum(billed_cost) as numeric(38, 9)) as billed_cost,
    cast(sum(effective_cost) as numeric(38, 9)) as effective_cost,
    cast(sum(list_cost) as numeric(38, 9)) as list_cost,
    cast(sum(coalesce(contracted_cost, 0)) as numeric(38, 9)) as contracted_cost
from {{ ref('int_charges_keyed') }}
{% if is_incremental() %}
where charge_date >= (
    select {{ dbt.dateadd('day', -var('cost_lookback_days'), 'max(charge_date)') }} from {{ this }}
)
{% endif %}
group by charge_date, account_key, service_key, region_key, charge_category, source_dataset
