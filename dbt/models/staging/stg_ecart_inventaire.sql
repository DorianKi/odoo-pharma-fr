select
    id as ecart_id,
    date(date, '{{ var("fuseau") }}') as jour,
    product_id as produit_id,
    case reason when 'cycle_count' then 'Inventaire tournant' else coalesce(reason, 'Autre') end as motif,
    theoretical_qty as quantite_theorique,
    counted_qty as quantite_comptee,
    gap_qty as ecart_quantite,
    unit_cost as cout_unitaire,
    gap_value as ecart_valeur
from {{ source('pharma_raw', 'inventory_gap') }}
