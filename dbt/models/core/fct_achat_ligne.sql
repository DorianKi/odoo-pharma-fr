-- Fait : une ligne de commande fournisseur.
select
    a.*,
    a.prix_unitaire_ht * a.quantite_commandee as montant_brut_ht,
    a.prix_unitaire_ht * a.quantite_commandee - a.montant_ht as remise_ht
from {{ ref('stg_achat_ligne') }} as a
