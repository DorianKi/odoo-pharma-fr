-- Rentabilité par mois et par article : CA, marge, stock moyen et rendement du stock.
with ventes as (
    select
        d.debut_mois, d.mois, l.produit_id,
        sum(l.quantite) as quantite,
        sum(l.ca_ht) as ca_ht,
        sum(l.cout_achat) as cout_achat,
        sum(l.marge) as marge,
        count(distinct l.patient_key) as patients
    from {{ ref('fct_vente_ligne') }} as l
    join {{ ref('dim_date') }} as d on d.jour = l.jour
    where not l.est_retourne
    group by d.debut_mois, d.mois, l.produit_id
),
stock as (
    select d.mois, s.produit_id, avg(s.valeur) as stock_moyen
    from {{ ref('fct_stock_jour') }} as s
    join {{ ref('dim_date') }} as d on d.jour = s.jour
    group by d.mois, s.produit_id
)
select
    v.debut_mois, v.mois, v.produit_id, p.libelle as article, p.rayon, p.laboratoire,
    p.statut_generique, p.classe_abc,
    v.quantite, v.ca_ht, v.cout_achat, v.marge, v.patients,
    safe_divide(v.marge, v.ca_ht) as taux_marge,
    s.stock_moyen,
    safe_divide(v.marge, s.stock_moyen) as gmroi_mois
from ventes as v
left join stock as s on s.mois = v.mois and s.produit_id = v.produit_id
left join {{ ref('mart_produits') }} as p on p.produit_id = v.produit_id
