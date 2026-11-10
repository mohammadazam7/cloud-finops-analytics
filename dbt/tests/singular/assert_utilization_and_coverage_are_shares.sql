select *
from {{ ref('fct_commitment_utilization') }}
where utilization not between 0 and 1 or coverage not between 0 and 1
