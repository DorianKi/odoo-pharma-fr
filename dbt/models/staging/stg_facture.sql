select
    id as facture_id,
    name as numero,
    case when move_type in ('out_invoice', 'out_refund') then 'Client' else 'Fournisseur' end as sens,
    move_type in ('out_refund', 'in_refund') as est_avoir,
    partner_id as partenaire_id,
    invoice_date as date_facture,
    invoice_date_due as date_echeance,
    case when move_type in ('out_refund', 'in_refund') then -amount_total else amount_total end as montant_ttc,
    case when move_type in ('out_refund', 'in_refund') then -amount_residual else amount_residual end as reste_du,
    payment_state as etat_paiement,
    paid_date as date_paiement
from {{ source('pharma_raw', 'invoice') }}
where payment_state != 'reversed'
