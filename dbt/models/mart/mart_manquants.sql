-- Manquants avec leurs trois axes : l'article (stock), le chiffre perdu (argent),
-- le patient et son statut de fidélité (patientèle).
select
    m.manquant_id, m.jour, d.mois, m.raison, m.issue, m.statut, m.quantite,
    m.ca_perdu_ttc, m.delai_jours, m.jour_delivrance,
    p.produit_id, p.libelle as article, p.rayon, p.laboratoire, p.classe_abc,
    coalesce(pr.specialite, 'Sans ordonnance') as specialite_prescripteur,
    m.patient_key,
    coalesce(mp.statut_fidelite, 'Client de passage') as statut_fidelite,
    coalesce(mp.tranche_age, 'Inconnue') as tranche_age
from {{ ref('fct_manquant') }} as m
join {{ ref('dim_date') }} as d on d.jour = m.jour
left join {{ ref('mart_produits') }} as p on p.produit_id = m.produit_id
left join {{ ref('dim_prescripteur') }} as pr on pr.prescripteur_id = m.prescripteur_id
left join {{ ref('mart_patients') }} as mp on mp.patient_key = m.patient_key
