-- Ground truth for the planted cost spikes, used only to score anomaly detection.
select
    cast(SubAccountId as {{ dbt.type_string() }}) as sub_account_id,
    cast(ServiceName as {{ dbt.type_string() }}) as service_name,
    cast(RegionId as {{ dbt.type_string() }}) as region_id,
    cast(first_day as date) as first_day,
    cast(last_day as date) as last_day,
    cast(factor as {{ dbt.type_float() }}) as factor
from {{ source('raw', 'synthetic_anomalies') }}
