-- Fait : une ligne délivrée (grain : article × passage). Les honoraires d'ordonnance,
-- portés par le passage, n'y figurent pas : les montants restent inférieurs à fct_passage.
select
    l.ligne_id, l.passage_id, p.jour, p.heure, p.patient_key, p.prescripteur_id, p.vendeur_id,
    case when p.est_vente_comptoir then 'Comptoir' else 'Ordonnance' end as type_vente,
    l.produit_id, l.produit_prescrit_id, l.quantite, l.en_rapport_ald, l.non_substituable,
    l.refus_substitution, l.est_substitution, l.est_generique, l.taux_remboursement,
    l.tiers_payant, l.est_retourne,
    l.ca_ttc, l.ca_ht, l.part_amo, l.part_amc, l.part_patient, l.honoraires_ht,
    l.cout_achat, l.marge
from {{ ref('stg_vente_ligne') }} as l
join {{ ref('stg_passage') }} as p on p.passage_id = l.passage_id
