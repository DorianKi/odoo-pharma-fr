select
    date as jour,
    inflow_amo as entree_amo,
    inflow_amc as entree_amc,
    inflow_other as entree_autre,
    outflow_suppliers as sortie_fournisseurs,
    net as flux_net,
    balance as solde_prevu
from {{ source('pharma_raw', 'cash_forecast') }}
