-- Fait : un passage en caisse (grain : ordonnance ou vente au comptoir).
-- Totaux honoraires compris : c'est la référence pour le chiffre et la marge de l'officine.
select
    passage_id, reference, jour, heure, delivre_le, patient_key, prescripteur_id, vendeur_id,
    case when est_vente_comptoir then 'Comptoir' else 'Ordonnance' end as type_vente,
    type_ordonnance, renouvellement, date_ordonnance, est_retourne,
    ca_ttc, ca_ht, part_amo, part_amc, part_patient, honoraires_ttc, cout_achat, marge
from {{ ref('stg_passage') }}
