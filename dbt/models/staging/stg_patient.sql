select
    patient_key,
    birth_year as annee_naissance,
    zip as code_postal,
    case exemption when 'ald' then 'ALD' when 'c2s' then 'C2S' else 'Régime général' end as regime,
    has_amc as a_complementaire,
    tiers_payant,
    is_anonymous as est_anonyme
from {{ source('pharma_raw', 'patient') }}
