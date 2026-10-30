-- Aucune clé patient ne doit ressembler à un NIR (13 ou 15 chiffres) : la clé est un HMAC.
select patient_key
from {{ ref('dim_patient') }}
where length(patient_key) != 20 or regexp_contains(patient_key, r'^[0-9]{13,15}$')
