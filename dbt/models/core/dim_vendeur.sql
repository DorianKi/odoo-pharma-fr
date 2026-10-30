-- Équipe ; est pharmacien celui qui réalise des missions de santé ou des délivrances sécurisées.
with pharmaciens as (
    select pharmacien_id as vendeur_id from {{ ref('stg_mission') }}
    union distinct
    select vendeur_id from {{ ref('stg_passage') }} where type_ordonnance = 'secure'
)
select
    v.vendeur_id,
    v.nom,
    v.est_actif,
    v.vendeur_id in (select vendeur_id from pharmaciens) as est_pharmacien
from {{ ref('stg_vendeur') }} as v
where v.vendeur_id in (select vendeur_id from {{ ref('stg_passage') }})
   or v.vendeur_id in (select vendeur_id from pharmaciens)
