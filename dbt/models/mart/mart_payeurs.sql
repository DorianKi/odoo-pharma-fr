-- Page « Argent » : délais réels de paiement par payeur et par fournisseur, encours et retards.
with reference as (
    select max(jour) as date_reference from {{ ref('fct_passage') }}
)
select
    pa.partenaire_id, pa.nom, pa.type_partenaire, f.sens,
    count(*) as factures,
    sum(f.montant_ttc) as montant_ttc,
    avg(f.delai_paiement_jours) as delai_moyen_jours,
    pa.delai_paiement_attendu,
    sum(case when f.reste_du != 0 then f.reste_du else 0 end) as encours,
    sum(case
            when f.reste_du != 0
             and coalesce(date_add(f.date_facture, interval pa.delai_paiement_attendu day),
                          f.date_echeance) < r.date_reference
            then f.reste_du else 0
        end) as encours_en_retard
from {{ ref('fct_facture') }} as f
cross join reference as r
join {{ ref('dim_partenaire') }} as pa on pa.partenaire_id = f.partenaire_id
group by pa.partenaire_id, pa.nom, pa.type_partenaire, f.sens, pa.delai_paiement_attendu
