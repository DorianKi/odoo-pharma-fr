-- Fait : un manquant (demande non servie), avec son issue : promis ou vente perdue.
select * from {{ ref('stg_manquant') }}
