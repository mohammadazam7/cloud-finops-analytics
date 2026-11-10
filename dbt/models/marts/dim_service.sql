-- One row per provider and service. A service is filed under the category most of its
-- lines use, because the FOCUS sample files a few services under more than one.
-- Services whose lines never name a category (a known gap in the sample) are
-- 'Unclassified' instead of null.
with counts as (

    select service_key, provider_name, service_name, service_category, count(*) as n
    from {{ ref('int_charges_keyed') }}
    group by service_key, provider_name, service_name, service_category

),

ranked as (

    select *, row_number() over (
        partition by service_key order by service_category is null, n desc, service_category
    ) as rn
    from counts

)

select
    service_key,
    provider_name,
    service_name,
    coalesce(service_category, 'Unclassified') as service_category
from ranked
where rn = 1
