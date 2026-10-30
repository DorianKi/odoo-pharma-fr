-- Affluence : passages par jour et par heure, et nombre de vendeurs qui ont encaissé.
select
    p.jour, d.jour_semaine, d.jour_semaine_num, d.mois, p.heure,
    count(*) as passages,
    sum(p.ca_ttc) as ca_ttc,
    count(distinct p.vendeur_id) as vendeurs_actifs,
    safe_divide(count(*), count(distinct p.vendeur_id)) as passages_par_vendeur
from {{ ref('fct_passage') }} as p
join {{ ref('dim_date') }} as d on d.jour = p.jour
where not p.est_retourne
group by p.jour, d.jour_semaine, d.jour_semaine_num, d.mois, p.heure
