-- Achats par commande : fournisseur, dépannages, remises et respect du franco de port.
select
    a.commande_id, a.reference_commande, a.jour, d.mois, a.origine, a.est_depannage,
    pa.nom as fournisseur, pa.type_partenaire as type_fournisseur, pa.franco_ht,
    count(*) as lignes,
    sum(a.montant_brut_ht) as montant_brut_ht,
    sum(a.remise_ht) as remise_ht,
    sum(a.montant_ht) as montant_ht,
    coalesce(sum(a.montant_ht) < pa.franco_ht, false) as sous_franco
from {{ ref('fct_achat_ligne') }} as a
join {{ ref('dim_date') }} as d on d.jour = a.jour
left join {{ ref('dim_partenaire') }} as pa on pa.partenaire_id = a.fournisseur_id
group by a.commande_id, a.reference_commande, a.jour, d.mois, a.origine, a.est_depannage,
         pa.nom, pa.type_partenaire, pa.franco_ht
