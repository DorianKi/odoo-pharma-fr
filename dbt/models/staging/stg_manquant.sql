select
    id as manquant_id,
    date(date, '{{ var("fuseau") }}') as jour,
    product_id as produit_id,
    patient_key,
    prescriber_id as prescripteur_id,
    quantity as quantite,
    case reason
        when 'stock' then 'Rupture officine'
        when 'national_shortage' then 'Rupture nationale'
        else coalesce(reason, 'Autre')
    end as raison,
    case outcome when 'deferred' then 'Promis' when 'lost' then 'Vente perdue' else outcome end as issue,
    case state
        when 'open' then 'À rendre'
        when 'delivered' then 'Rendu'
        when 'cancelled' then 'Abandonné'
        else 'Clos'
    end as statut,
    unit_price as prix_unitaire_ttc,
    amount_lost as ca_perdu_ttc,
    date(delivered_date, '{{ var("fuseau") }}') as jour_delivrance,
    delay_days as delai_jours
from {{ source('pharma_raw', 'missing_item') }}
