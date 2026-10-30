select
    id as ligne_achat_id,
    order_id as commande_id,
    order_name as reference_commande,
    coalesce(origin, '') as origine,
    lower(coalesce(origin, '')) like '%dépannage%' as est_depannage,
    state as statut,
    partner_id as fournisseur_id,
    date(coalesce(date_approve, date_order), '{{ var("fuseau") }}') as jour,
    product_id as produit_id,
    product_qty as quantite_commandee,
    qty_received as quantite_recue,
    price_unit as prix_unitaire_ht,
    discount as remise_pct,
    price_subtotal as montant_ht
from {{ source('pharma_raw', 'purchase_line') }}
where state in ('purchase', 'done')
