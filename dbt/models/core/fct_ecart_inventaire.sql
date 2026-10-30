-- Fait : un écart constaté à l'inventaire (démarque inconnue).
select * from {{ ref('stg_ecart_inventaire') }}
