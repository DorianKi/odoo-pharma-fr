-- Table large pour Looker Studio : chaque ligne vendue porte ses trois axes
-- (stock : article, rayon, classe ABC, couverture ; argent : CA, marge, payeurs ;
-- patientèle : tranche d'âge, régime, statut de fidélité). Un clic sur un axe filtre les autres.
select
    l.ligne_id, l.passage_id, l.jour, d.mois, d.jour_semaine, d.jour_semaine_num, l.heure,
    l.type_vente,
    coalesce(v.nom, 'Inconnu') as vendeur,
    coalesce(pr.nom, 'Sans ordonnance') as prescripteur,
    coalesce(pr.specialite, 'Sans ordonnance') as specialite_prescripteur,
    l.patient_key,
    coalesce(pa.tranche_age, 'Inconnue') as tranche_age,
    coalesce(pa.regime, 'Inconnu') as regime,
    coalesce(mp.statut_fidelite, 'Client de passage') as statut_fidelite,
    coalesce(mp.est_chronique, false) as patient_chronique,
    l.produit_id, p.libelle as article, p.rayon, p.laboratoire, p.statut_generique,
    p.classe_abc, p.couverture_jours as couverture_actuelle_jours,
    p.est_en_rupture as en_rupture_actuellement,
    l.est_generique, l.est_substitution, l.non_substituable, l.refus_substitution,
    l.quantite, l.ca_ttc, l.ca_ht, l.marge, l.cout_achat, l.part_amo, l.part_amc,
    l.part_patient, l.honoraires_ht
from {{ ref('fct_vente_ligne') }} as l
join {{ ref('dim_date') }} as d on d.jour = l.jour
left join {{ ref('mart_produits') }} as p on p.produit_id = l.produit_id
left join {{ ref('dim_vendeur') }} as v on v.vendeur_id = l.vendeur_id
left join {{ ref('dim_prescripteur') }} as pr on pr.prescripteur_id = l.prescripteur_id
left join {{ ref('dim_patient') }} as pa on pa.patient_key = l.patient_key
left join {{ ref('mart_patients') }} as mp on mp.patient_key = l.patient_key
where not l.est_retourne
