select id as vendeur_id, name as nom, active as est_actif
from {{ source('pharma_raw', 'staff') }}
