-- Patients pseudonymisés : tranche d'âge et régime, jamais l'identité.
with reference as (
    select extract(year from max(jour)) as annee from {{ ref('stg_passage') }}
)
select
    p.patient_key,
    p.annee_naissance,
    case
        when p.annee_naissance is null then 'Inconnue'
        when r.annee - p.annee_naissance < 18 then '0-17 ans'
        when r.annee - p.annee_naissance < 40 then '18-39 ans'
        when r.annee - p.annee_naissance < 60 then '40-59 ans'
        when r.annee - p.annee_naissance < 75 then '60-74 ans'
        else '75 ans et plus'
    end as tranche_age,
    p.code_postal,
    p.regime,
    p.a_complementaire,
    p.tiers_payant,
    p.est_anonyme
from {{ ref('stg_patient') }} as p
cross join reference as r
