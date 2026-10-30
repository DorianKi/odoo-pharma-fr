-- Page « Stock » : un article par ligne, état à la date de référence : stock, couverture,
-- surstock, péremptions, classe ABC sur 90 jours de marge, rendement du stock, manquants.
with reference as (
    select max(jour) as date_reference from {{ ref('fct_passage') }}
),
ventes as (
    select
        l.produit_id,
        sum(l.quantite) as quantite_90j,
        sum(l.ca_ht) as ca_ht_90j,
        sum(l.marge) as marge_90j,
        count(distinct l.patient_key) as patients_90j
    from {{ ref('fct_vente_ligne') }} as l
    cross join reference as r
    where not l.est_retourne and l.jour > date_sub(r.date_reference, interval 90 day)
    group by l.produit_id
),
classement as (
    select
        produit_id,
        safe_divide(
            sum(marge_90j) over (order by marge_90j desc, produit_id rows between unbounded preceding and current row) - marge_90j,
            sum(marge_90j) over ()
        ) as part_cumulee_avant
    from ventes
    where marge_90j > 0
),
dernier_stock as (
    select s.*
    from {{ ref('fct_stock_jour') }} as s
    where s.jour = (select max(jour) from {{ ref('fct_stock_jour') }})
),
stock_moyen as (
    select s.produit_id, avg(s.valeur) as valeur_stock_moyenne_90j
    from {{ ref('fct_stock_jour') }} as s
    cross join reference as r
    where s.jour > date_sub(r.date_reference, interval 90 day)
    group by s.produit_id
),
manquants as (
    select m.produit_id, count(*) as manquants_30j, sum(m.ca_perdu_ttc) as ca_perdu_30j
    from {{ ref('fct_manquant') }} as m
    cross join reference as r
    where m.jour > date_sub(r.date_reference, interval 30 day)
    group by m.produit_id
),
ecarts as (
    select e.produit_id, sum(e.ecart_valeur) as ecart_inventaire_90j
    from {{ ref('fct_ecart_inventaire') }} as e
    cross join reference as r
    where e.jour > date_sub(r.date_reference, interval 90 day)
    group by e.produit_id
)
select
    p.produit_id, p.cip13, p.libelle, p.rayon, p.laboratoire, p.statut_generique,
    p.groupe_generique, p.est_substituable, p.prix_public_ttc, p.disponibilite_nationale,
    case
        when c.part_cumulee_avant < 0.80 then 'A'
        when c.part_cumulee_avant < 0.95 then 'B'
        when v.produit_id is not null then 'C'
        else 'Sans vente'
    end as classe_abc,
    coalesce(v.quantite_90j, 0) as quantite_vendue_90j,
    coalesce(v.ca_ht_90j, 0) as ca_ht_90j,
    coalesce(v.marge_90j, 0) as marge_90j,
    coalesce(v.patients_90j, 0) as patients_90j,
    s.quantite as stock_quantite,
    s.valeur as stock_valeur,
    s.demande_jour,
    s.couverture_jours,
    s.valeur_surstock,
    s.valeur_perime_90j,
    s.est_dormant,
    s.est_en_rupture,
    s.rupture_nationale,
    s.derniere_vente,
    sm.valeur_stock_moyenne_90j,
    safe_divide(coalesce(v.marge_90j, 0) * 365 / 90, sm.valeur_stock_moyenne_90j) as gmroi_annuel,
    coalesce(mq.manquants_30j, 0) as manquants_30j,
    coalesce(mq.ca_perdu_30j, 0) as ca_perdu_30j,
    coalesce(e.ecart_inventaire_90j, 0) as ecart_inventaire_90j
from {{ ref('dim_produit') }} as p
left join ventes as v on v.produit_id = p.produit_id
left join classement as c on c.produit_id = p.produit_id
left join dernier_stock as s on s.produit_id = p.produit_id
left join stock_moyen as sm on sm.produit_id = p.produit_id
left join manquants as mq on mq.produit_id = p.produit_id
left join ecarts as e on e.produit_id = p.produit_id
where not p.est_honoraire
