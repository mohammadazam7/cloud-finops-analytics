with days as (

    {{ dbt.date_spine('day',
        "cast('" ~ var('calendar_start') ~ "' as date)",
        "cast('" ~ var('calendar_end') ~ "' as date)") }}

)

select
    cast(date_day as date) as date_day,
    extract(year from date_day) as year,
    extract(month from date_day) as month,
    {{ dbt.date_trunc('month', 'date_day') }} as month_start,
    {{ dbt.date_trunc('week', 'date_day') }} as week_start
from days
