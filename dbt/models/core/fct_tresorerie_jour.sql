-- Fait journalier : encaissements par type de payeur, décaissements et solde bancaire.
with mouvements as (
    select
        m.jour,
        sum(case when pa.type_partenaire = 'Assurance maladie' then m.entree else 0 end) as entree_amo,
        sum(case when pa.type_partenaire = 'Complémentaire' then m.entree else 0 end) as entree_amc,
        sum(case when pa.type_partenaire is null
                   or pa.type_partenaire not in ('Assurance maladie', 'Complémentaire')
                 then m.entree else 0 end) as entree_autre,
        sum(m.entree) as entrees,
        sum(m.sortie) as sorties
    from {{ ref('stg_mouvement_tresorerie') }} as m
    left join {{ ref('stg_partenaire') }} as pa on pa.partenaire_id = m.partenaire_id
    group by m.jour
),
jours as (
    select jour from {{ ref('dim_date') }}
    where jour <= (select max(jour) from {{ ref('stg_passage') }})
)
select
    j.jour,
    coalesce(m.entree_amo, 0) as entree_amo,
    coalesce(m.entree_amc, 0) as entree_amc,
    coalesce(m.entree_autre, 0) as entree_autre,
    coalesce(m.entrees, 0) as entrees,
    coalesce(m.sorties, 0) as sorties,
    coalesce(m.entrees, 0) - coalesce(m.sorties, 0) as flux_net,
    sum(coalesce(m.entrees, 0) - coalesce(m.sorties, 0)) over (order by j.jour) as solde
from jours as j
left join mouvements as m on m.jour = j.jour
