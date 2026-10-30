-- Page « Argent » : trésorerie réelle jour par jour, créances et dettes ouvertes,
-- prolongée par la prévision à 60 jours.
with reference as (
    select max(jour) as date_reference from {{ ref('fct_passage') }}
),
dernier_solde as (
    select t.solde
    from {{ ref('fct_tresorerie_jour') }} as t
    where t.jour = (select max(jour) from {{ ref('fct_tresorerie_jour') }})
),
encours as (
    select
        t.jour,
        sum(case when f.sens = 'Client' then f.montant_ttc else 0 end) as creances_ouvertes,
        sum(case when f.sens = 'Fournisseur' then f.montant_ttc else 0 end) as dettes_ouvertes
    from {{ ref('fct_tresorerie_jour') }} as t
    join {{ ref('fct_facture') }} as f
      on f.date_facture <= t.jour and (f.date_paiement is null or f.date_paiement > t.jour)
    group by t.jour
)
select
    t.jour, 'Réel' as nature,
    t.entree_amo, t.entree_amc, t.entree_autre, t.entrees, t.sorties, t.flux_net,
    t.solde,
    coalesce(e.creances_ouvertes, 0) as creances_ouvertes,
    coalesce(e.dettes_ouvertes, 0) as dettes_ouvertes
from {{ ref('fct_tresorerie_jour') }} as t
left join encours as e on e.jour = t.jour
union all
select
    p.jour, 'Prévision' as nature,
    p.entree_amo, p.entree_amc, p.entree_autre,
    p.entree_amo + p.entree_amc + p.entree_autre as entrees,
    p.sortie_fournisseurs as sorties,
    p.flux_net,
    -- Repart du solde réel du dernier jour : la prévision prolonge la courbe réelle.
    ds.solde + sum(p.flux_net) over (order by p.jour) as solde,
    cast(null as numeric) as creances_ouvertes,
    cast(null as numeric) as dettes_ouvertes
from {{ ref('fct_prevision_tresorerie') }} as p
cross join reference as r
cross join dernier_solde as ds
where p.jour > r.date_reference
