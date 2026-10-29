{
    "name": "Pharmacie FR - Réglementaire",
    "summary": "Registre des stupéfiants, ordonnancier, gestion des périmés "
               "(destruction) et retours patients (avoirs, retour en stock ou destruction)",
    "version": "19.0.1.0.0",
    "category": "Inventory/Pharmacy",
    "author": "Dorian Kihouba",
    "website": "https://github.com/DorianKi/odoo-pharma-fr",
    "license": "LGPL-3",
    "depends": [
        "pharma_fr_dispensation",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/pharma_regulatory_security.xml",
        "data/ir_sequence_data.xml",
        "data/stock_scrap_reason_data.xml",
        "report/pharma_register_reports.xml",
        "wizard/pharma_expiry_scrap_wizard_views.xml",
        "wizard/pharma_prescription_return_wizard_views.xml",
        "views/pharma_narcotic_register_views.xml",
        "views/pharma_ordonnancier_views.xml",
        "views/stock_quant_views.xml",
        "views/pharma_prescription_views.xml",
        "views/pharma_regulatory_menus.xml",
    ],
    "installable": True,
}
