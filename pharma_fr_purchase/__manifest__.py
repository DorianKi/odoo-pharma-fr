{
    "name": "Pharmacie FR - Achats",
    "summary": "Achats d'officine : grossistes-répartiteurs et commandes directes "
               "laboratoires, conditions commerciales, plafonds légaux de remise, "
               "franco, seuils de réassort calculés sur les ventes",
    "version": "19.0.1.0.0",
    "category": "Inventory/Pharmacy",
    "author": "Dorian Kihouba",
    "website": "https://github.com/DorianKi/odoo-pharma-fr",
    "license": "LGPL-3",
    "depends": [
        "pharma_fr_base",
        "purchase_stock",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/pharma_purchase_security.xml",
        "data/pharma_discount_cap_data.xml",
        "views/pharma_discount_cap_views.xml",
        "views/pharma_purchase_agreement_views.xml",
        "views/purchase_order_views.xml",
        "views/res_partner_views.xml",
        "views/product_template_views.xml",
        "wizard/pharma_replenishment_wizard_views.xml",
        "views/pharma_purchase_menus.xml",
    ],
    "installable": True,
}
