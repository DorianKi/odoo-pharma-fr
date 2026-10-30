-- Un passage en caisse : ordonnance ou vente au comptoir, à l'heure de Paris.
select
    id as passage_id,
    name as reference,
    state = 'returned' as est_retourne,
    patient_key,
    prescriber_id as prescripteur_id,
    seller_id as vendeur_id,
    prescriber_id is null as est_vente_comptoir,
    prescription_type as type_ordonnance,
    renewal_index as renouvellement,
    prescription_date as date_ordonnance,
    datetime(dispensing_date, '{{ var("fuseau") }}') as delivre_le,
    date(dispensing_date, '{{ var("fuseau") }}') as jour,
    extract(hour from datetime(dispensing_date, '{{ var("fuseau") }}')) as heure,
    amount_total as ca_ttc,
    amount_untaxed as ca_ht,
    amount_amo as part_amo,
    amount_amc as part_amc,
    amount_patient as part_patient,
    amount_fees as honoraires_ttc,
    amount_cost as cout_achat,
    margin as marge
from {{ source('pharma_raw', 'prescription') }}
