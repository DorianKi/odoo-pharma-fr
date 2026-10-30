-- Missions de santé : type, pharmacien, patient (tranche d'âge) et montants.
select
    m.mission_id, m.jour, d.mois, d.jour_semaine, m.categorie, m.type_mission,
    v.nom as pharmacien, coalesce(pa.tranche_age, 'Inconnue') as tranche_age,
    m.duree_minutes, m.montant, m.part_amo, m.part_amc, m.part_patient
from {{ ref('fct_mission') }} as m
join {{ ref('dim_date') }} as d on d.jour = m.jour
left join {{ ref('dim_vendeur') }} as v on v.vendeur_id = m.pharmacien_id
left join {{ ref('dim_patient') }} as pa on pa.patient_key = m.patient_key
