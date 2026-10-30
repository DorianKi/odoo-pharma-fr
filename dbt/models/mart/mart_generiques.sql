-- Substitution générique par prescripteur et par mois (lignes du répertoire des génériques).
select
    d.debut_mois, d.mois, pr.prescripteur_id, pr.nom as prescripteur, pr.specialite,
    count(*) as lignes_substituables,
    countif(l.est_generique) as lignes_generiques,
    countif(l.non_substituable) as mentions_non_substituable,
    countif(l.refus_substitution) as refus_patient,
    safe_divide(countif(l.est_generique), count(*)) as taux_substitution,
    sum(case when not l.est_generique then l.ca_ht else 0 end) as ca_ht_princeps
from {{ ref('fct_vente_ligne') }} as l
join {{ ref('dim_produit') }} as p on p.produit_id = l.produit_id
join {{ ref('dim_prescripteur') }} as pr on pr.prescripteur_id = l.prescripteur_id
join {{ ref('dim_date') }} as d on d.jour = l.jour
where p.est_substituable and not l.est_retourne
group by d.debut_mois, d.mois, pr.prescripteur_id, pr.nom, pr.specialite
