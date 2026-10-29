{
    "name": "Pharmacie FR - Base produits (BDPM)",
    "summary": "Référentiel médicament français : import de la Base de Données "
               "Publique des Médicaments, fiches article officine (CIP13, "
               "remboursement, génériques, listes, TVA)",
    "version": "19.0.1.0.0",
    "category": "Inventory/Pharmacy",
    "author": "Dorian Kihouba",
    "website": "https://github.com/DorianKi/odoo-pharma-fr",
    "license": "LGPL-3",
    "depends": [
        "account",
        "stock",
        "product_expiry",
    ],
    "data": [
        "security/pharma_security.xml",
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "views/pharma_specialite_views.xml",
        "views/pharma_presentation_views.xml",
        "views/pharma_generic_group_views.xml",
        "views/product_template_views.xml",
        "views/res_partner_views.xml",
        "wizard/pharma_bdpm_import_wizard_views.xml",
        "views/pharma_menus.xml",
    ],
    "application": True,
    "installable": True,
}
