from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    pharma_payment_delay_days = fields.Integer(
        "Délai de paiement constaté (jours)",
        help="Délai moyen entre la facture et le règlement de cet organisme ; sert à la "
             "trésorerie prévisionnelle. 0 : valeur par défaut selon le type (AMO 5 j, AMC 20 j).",
    )

    def _pharma_expected_delay(self):
        self.ensure_one()
        if self.pharma_payment_delay_days:
            return self.pharma_payment_delay_days
        return {"amo": 5, "amc": 20}.get(self.pharma_insurer_type, 0)
