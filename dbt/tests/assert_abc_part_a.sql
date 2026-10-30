-- La classe A porte au moins 80 % de la marge des articles vendus avec marge positive.
select 1
from (
    select safe_divide(sum(case when classe_abc = 'A' then marge_90j else 0 end),
                       sum(case when marge_90j > 0 then marge_90j else 0 end)) as part_a
    from {{ ref('mart_produits') }}
) as x
where x.part_a < 0.80
