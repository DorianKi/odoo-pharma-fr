-- Les lignes d'un passage ne peuvent pas dépasser son total (les honoraires d'ordonnance
-- ne sont portés que par le passage).
select l.passage_id
from {{ ref('fct_vente_ligne') }} as l
join {{ ref('fct_passage') }} as p on p.passage_id = l.passage_id
group by l.passage_id, p.ca_ttc
having sum(l.ca_ttc) > p.ca_ttc + 0.01
