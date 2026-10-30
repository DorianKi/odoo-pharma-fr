-- Page « Stock », évolution : un article par jour, avec ses attributs pour filtrer.
select
    s.jour, d.mois, s.produit_id, p.libelle as article, p.rayon, p.laboratoire,
    p.statut_generique, p.classe_abc,
    s.quantite, s.valeur, s.demande_jour, s.couverture_jours, s.valeur_surstock,
    s.valeur_perime_90j, s.quantite_perimee, s.valeur_dormante, s.est_dormant,
    s.est_en_rupture, s.rupture_nationale
from {{ ref('fct_stock_jour') }} as s
join {{ ref('dim_date') }} as d on d.jour = s.jour
join {{ ref('mart_produits') }} as p on p.produit_id = s.produit_id
