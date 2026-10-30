select
    id as partenaire_id,
    name as nom,
    case
        when partner_type = 'wholesaler' then 'Grossiste'
        when partner_type = 'laboratory' then 'Laboratoire'
        when insurer_type = 'amo' then 'Assurance maladie'
        when insurer_type = 'amc' then 'Complémentaire'
        else 'Comptoir'
    end as type_partenaire,
    payment_delay_days as delai_paiement_attendu,
    franco_amount as franco_ht,
    is_main_wholesaler as est_grossiste_principal
from {{ source('pharma_raw', 'partner') }}
