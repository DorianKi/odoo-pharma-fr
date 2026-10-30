-- Fait journalier : stock de chaque article chaque soir.
-- Surstock = valeur au-delà de 30 jours de demande ; un article sans demande est
-- entièrement en surstock.
select
    s.*,
    s.cout_unitaire * greatest(s.quantite - 30 * coalesce(s.demande_jour, 0), 0) as valeur_surstock,
    case when s.est_dormant then s.valeur else 0 end as valeur_dormante
from {{ ref('stg_stock_jour') }} as s
