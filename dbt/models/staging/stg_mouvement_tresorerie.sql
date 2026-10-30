select
    id as mouvement_id,
    date as jour,
    journal_type as type_journal,
    partner_id as partenaire_id,
    debit as entree,
    credit as sortie
from {{ source('pharma_raw', 'cash_line') }}
