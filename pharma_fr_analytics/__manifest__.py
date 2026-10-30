{
    "name": "Pharmacie FR - Pilotage",
    "summary": "Pilotage de l'officine : photos quotidiennes du stock, trésorerie "
               "prévisionnelle, écarts d'inventaire, fidélité, rentabilité ABC, "
               "génériques par prescripteur, équipe et affluence",
    "version": "19.0.1.0.0",
    "category": "Inventory/Pharmacy",
    "author": "Dorian Kihouba",
    "website": "https://github.com/DorianKi/odoo-pharma-fr",
    "license": "LGPL-3",
    "depends": [
        "pharma_fr_purchase",
        "pharma_fr_regulatory",
        "pharma_fr_services",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "views/pharma_stock_snapshot_views.xml",
        "views/pharma_analytics_views.xml",
    ],
    "installable": True,
}
