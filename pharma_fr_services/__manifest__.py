{
    "name": "Pharmacie FR - Missions de santé",
    "summary": "Vaccinations, tests rapides (TROD), bilans partagés de médication et "
               "entretiens pharmaceutiques : réalisation, honoraires et facturation",
    "version": "19.0.1.0.0",
    "category": "Inventory/Pharmacy",
    "author": "Dorian Kihouba",
    "website": "https://github.com/DorianKi/odoo-pharma-fr",
    "license": "LGPL-3",
    "depends": ["pharma_fr_dispensation"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "data/pharma_health_service_type_data.xml",
        "views/pharma_health_service_views.xml",
    ],
    "installable": True,
}
