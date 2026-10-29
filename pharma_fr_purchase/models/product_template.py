from odoo import api, fields, models

GENERIC_TYPES = ("generic", "generic_posology", "generic_substitutable")


class ProductTemplate(models.Model):
    _inherit = "product.template"

    pharma_is_biosimilar = fields.Boolean(
        "Biosimilaire substituable",
        help="Plafond de remise spécifique aux biosimilaires.",
    )
    pharma_discount_cap_category = fields.Selection(
        [
            ("none", "Non plafonné (prix libre)"),
            ("base", "Remboursable (cas général)"),
            ("generic", "Générique"),
            ("biosimilar", "Biosimilaire"),
        ],
        string="Plafond de remise applicable",
        compute="_compute_pharma_discount_cap_category",
        store=True,
    )

    @api.depends("pharma_category", "pharma_generic_type", "pharma_is_biosimilar")
    def _compute_pharma_discount_cap_category(self):
        for tmpl in self:
            if tmpl.pharma_category != "drug_reimbursed":
                tmpl.pharma_discount_cap_category = "none"
            elif tmpl.pharma_is_biosimilar:
                tmpl.pharma_discount_cap_category = "biosimilar"
            elif tmpl.pharma_generic_type in GENERIC_TYPES:
                tmpl.pharma_discount_cap_category = "generic"
            else:
                tmpl.pharma_discount_cap_category = "base"
