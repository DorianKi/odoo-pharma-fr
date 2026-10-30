select
    date as jour,
    product_id as produit_id,
    quantity as quantite,
    unit_cost as cout_unitaire,
    value as valeur,
    sales_30d as ventes_30j,
    daily_demand as demande_jour,
    coverage_days as couverture_jours,
    qty_expiring_90d as quantite_perime_90j,
    value_expiring_90d as valeur_perime_90j,
    qty_expired as quantite_perimee,
    last_sale_date as derniere_vente,
    is_dormant as est_dormant,
    is_out_of_stock as est_en_rupture,
    national_shortage as rupture_nationale
from {{ source('pharma_raw', 'stock_snapshot') }}
