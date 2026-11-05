-- Every row from the synthetic history must be marked synthetic, and no sample row may be.
select source_dataset, is_synthetic, count(*) as n
from {{ ref('stg_billing_charges') }}
group by source_dataset, is_synthetic
having (source_dataset = 'synthetic_charges') <> is_synthetic
