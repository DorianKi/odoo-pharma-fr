-- Fait journalier : prévision de trésorerie à 60 jours calculée par Odoo le jour de l export.
select * from {{ ref('stg_prevision_tresorerie') }}
