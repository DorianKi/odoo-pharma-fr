-- Calendrier : un jour par ligne, du premier jour d'activité à la fin de la prévision.
with jours as (
    select jour from {{ ref('stg_passage') }}
    union all select jour from {{ ref('stg_stock_jour') }}
    union all select jour from {{ ref('stg_mouvement_tresorerie') }}
    union all select jour from {{ ref('stg_prevision_tresorerie') }}
),
bornes as (
    select min(jour) as debut, max(jour) as fin from jours
)
select
    d as jour,
    extract(year from d) as annee,
    extract(quarter from d) as trimestre,
    extract(month from d) as mois_num,
    format_date('%Y-%m', d) as mois,
    date_trunc(d, month) as debut_mois,
    extract(isoweek from d) as semaine_iso,
    date_trunc(d, isoweek) as debut_semaine,
    mod(extract(dayofweek from d) + 5, 7) + 1 as jour_semaine_num,
    case mod(extract(dayofweek from d) + 5, 7) + 1
        when 1 then 'Lundi' when 2 then 'Mardi' when 3 then 'Mercredi' when 4 then 'Jeudi'
        when 5 then 'Vendredi' when 6 then 'Samedi' else 'Dimanche'
    end as jour_semaine,
    case extract(month from d)
        when 1 then 'janvier' when 2 then 'février' when 3 then 'mars' when 4 then 'avril'
        when 5 then 'mai' when 6 then 'juin' when 7 then 'juillet' when 8 then 'août'
        when 9 then 'septembre' when 10 then 'octobre' when 11 then 'novembre'
        else 'décembre'
    end as libelle_mois,
    extract(dayofweek from d) != 1 as est_ouvre
from unnest(generate_date_array((select debut from bornes), (select fin from bornes))) as d
