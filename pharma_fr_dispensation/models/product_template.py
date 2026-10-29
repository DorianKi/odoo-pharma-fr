from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    pharma_is_fee = fields.Boolean(
        "Article d'honoraire", help="Article de facturation d'un honoraire."
    )

    @api.model
    def _pharma_ensure_fee_taxes(self):
        """Les honoraires de dispensation suivent la TVA des médicaments
        remboursables (2,1 %) : impose cette taxe pour la société courante."""
        tax = self._pharma_find_tax("2.1", "sale", price_include=True)
        if not tax:
            return
        fees = self.with_context(active_test=False).search([("pharma_is_fee", "=", True)])
        for fee in fees:
            company_taxes = fee.taxes_id.filtered(lambda t: t.company_id == tax.company_id)
            if company_taxes != tax:
                fee.sudo().taxes_id = [(3, t.id) for t in company_taxes] + [(4, tax.id)]
