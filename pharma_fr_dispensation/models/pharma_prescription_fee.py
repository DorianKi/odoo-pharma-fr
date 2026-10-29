from odoo import fields, models


class PharmaPrescriptionFee(models.Model):
    _name = "pharma.prescription.fee"
    _description = "Honoraire facturé sur une ordonnance"
    _order = "prescription_id, id"

    prescription_id = fields.Many2one(
        "pharma.prescription", required=True, ondelete="cascade", index=True
    )
    currency_id = fields.Many2one(related="prescription_id.currency_id")
    rule_id = fields.Many2one("pharma.fee.rule", required=True, ondelete="restrict")
    code = fields.Selection(related="rule_id.code", store=True)
    product_id = fields.Many2one(related="rule_id.product_id")
    amount_total = fields.Monetary("Montant TTC")
    reimbursement_rate = fields.Float("Taux AMO appliqué (%)")
    amount_amo = fields.Monetary("Part AMO")
    amount_amc = fields.Monetary("Part AMC")
    amount_patient = fields.Monetary("Part patient")
