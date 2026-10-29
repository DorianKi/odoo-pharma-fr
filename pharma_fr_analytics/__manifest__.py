{
    "name": "Pharmacie FR - Pilotage",
    "summary": "Photos quotidiennes du stock (valeur, couverture, péremptions, dormants, "
               "ruptures) pour le suivi et l'analyse de l'officine",
    "version": "19.0.1.0.0",
    "category": "Inventory/Pharmacy",
    "author": "Dorian Kihouba",
    "website": "https://github.com/DorianKi/odoo-pharma-fr",
    "license": "LGPL-3",
    "depends": [
        "pharma_fr_purchase",
        "pharma_fr_regulatory",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "views/pharma_stock_snapshot_views.xml",
    ],
    "installable": True,
}
