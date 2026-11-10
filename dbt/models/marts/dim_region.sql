select distinct
    region_key,
    provider_name,
    coalesce(region_id, 'global') as region_id
from {{ ref('int_charges_keyed') }}
