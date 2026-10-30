-- Le dernier solde réel égale la somme de tous les mouvements bancaires.
select 1
from (select solde from {{ ref('fct_tresorerie_jour') }}
      where jour = (select max(jour) from {{ ref('fct_tresorerie_jour') }})) as s
cross join (select sum(entree) - sum(sortie) as total from {{ ref('stg_mouvement_tresorerie') }}
            where jour <= (select max(jour) from {{ ref('fct_tresorerie_jour') }})) as m
where abs(s.solde - m.total) > 0.01
