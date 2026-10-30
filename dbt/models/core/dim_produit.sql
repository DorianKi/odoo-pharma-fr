-- Articles : rayon, laboratoire, statut générique, prix et disponibilité nationale.
select * from {{ ref('stg_produit') }}
