-- Le CA de la page Journée doit égaler la somme des passages non retournés.
select 1
from (select sum(ca_ttc) as total from {{ ref('mart_journee') }}) as j
cross join (select sum(ca_ttc) as total from {{ ref('fct_passage') }} where not est_retourne) as p
where abs(j.total - p.total) > 0.01
