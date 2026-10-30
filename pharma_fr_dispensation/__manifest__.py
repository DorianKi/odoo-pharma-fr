{
    "name": "Pharmacie FR - Dispensation",
    "summary": "Dispensation sur ordonnance : patients (NIR, AMO, AMC, ALD, C2S), "
               "prescripteurs (RPPS), tiers payant, honoraires de dispensation, "
               "substitution générique, sortie de stock FEFO et facturation par payeur",
    "version": "19.0.1.3.0",
    "category": "Inventory/Pharmacy",
    "author": "Dorian Kihouba",
    "website": "https://github.com/DorianKi/odoo-pharma-fr",
    "license": "LGPL-3",
    "depends": [
        "pharma_fr_base",
        "l10n_fr_account",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/pharma_dispensation_security.xml",
        "data/ir_sequence_data.xml",
        "data/product_data.xml",
        "data/pharma_fee_rule_data.xml",
        "data/ir_cron_data.xml",
        "views/res_company_views.xml",
        "views/res_partner_views.xml",
        "views/pharma_fee_rule_views.xml",
        "views/pharma_prescription_views.xml",
        "views/pharma_missing_item_views.xml",
        "views/pharma_dispensation_menus.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
}
