select
    id as prescripteur_id,
    name as nom,
    rpps,
    coalesce(specialty, 'Non renseignée') as specialite,
    zip as code_postal
from {{ source('pharma_raw', 'prescriber') }}
