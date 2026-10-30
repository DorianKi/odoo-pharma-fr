-- Fait : une facture client (bordereau AMO, AMC, comptoir) ou fournisseur.
select
    f.*,
    case when f.date_paiement is not null
         then date_diff(f.date_paiement, f.date_facture, day) end as delai_paiement_jours
from {{ ref('stg_facture') }} as f
