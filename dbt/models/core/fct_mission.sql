-- Fait : une mission de santé réalisée.
select * from {{ ref('stg_mission') }}
