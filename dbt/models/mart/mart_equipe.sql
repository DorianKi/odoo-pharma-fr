-- Équipe : activité par vendeur et par jour, dont le conseil associé aux ordonnances
-- (parapharmacie et médicaments non remboursables ajoutés à une ordonnance).
with conseil as (
    select
        l.jour, l.vendeur_id,
        count(*) as lignes_conseil,
        sum(l.ca_ttc) as ca_conseil_ttc,
        sum(l.marge) as marge_conseil
    from {{ ref('fct_vente_ligne') }} as l
    join {{ ref('dim_produit') }} as p on p.produit_id = l.produit_id
    where l.type_vente = 'Ordonnance' and not l.est_retourne
      and p.rayon in ('Parapharmacie', 'Médicament non remboursable')
    group by l.jour, l.vendeur_id
),
passages as (
    select
        jour, vendeur_id,
        count(*) as passages,
        countif(type_vente = 'Ordonnance') as ordonnances,
        sum(ca_ttc) as ca_ttc,
        sum(marge) as marge
    from {{ ref('fct_passage') }}
    where not est_retourne
    group by jour, vendeur_id
),
missions as (
    select jour, pharmacien_id as vendeur_id, count(*) as missions, sum(montant) as ca_missions
    from {{ ref('fct_mission') }}
    group by jour, pharmacien_id
),
cles as (
    select jour, vendeur_id from passages
    union distinct
    select jour, vendeur_id from missions
)
select
    k.jour, d.mois, d.jour_semaine, v.nom as vendeur, v.est_pharmacien,
    coalesce(p.passages, 0) as passages,
    coalesce(p.ordonnances, 0) as ordonnances,
    coalesce(p.ca_ttc, 0) as ca_ttc,
    coalesce(p.marge, 0) as marge,
    coalesce(c.lignes_conseil, 0) as lignes_conseil,
    coalesce(c.ca_conseil_ttc, 0) as ca_conseil_ttc,
    coalesce(c.marge_conseil, 0) as marge_conseil,
    coalesce(m.missions, 0) as missions,
    coalesce(m.ca_missions, 0) as ca_missions
from cles as k
join {{ ref('dim_date') }} as d on d.jour = k.jour
join {{ ref('dim_vendeur') }} as v on v.vendeur_id = k.vendeur_id
left join passages as p on p.jour = k.jour and p.vendeur_id = k.vendeur_id
left join conseil as c on c.jour = k.jour and c.vendeur_id = k.vendeur_id
left join missions as m on m.jour = k.jour and m.vendeur_id = k.vendeur_id
