from odoo import fields, models


class PharmaPrescriptionReturnWizard(models.TransientModel):
    _name = "pharma.prescription.return.wizard"
    _description = "Retour patient"

    prescription_id = fields.Many2one("pharma.prescription", required=True)
    reason = fields.Char("Motif", required=True)
    restock = fields.Boolean(
        "Remettre en stock",
        help="Uniquement si le produit n'a pas quitté l'officine (erreur au comptoir). "
             "Sinon, les produits retournés sont détruits.",
    )

    def action_confirm(self):
        self.prescription_id._pharma_return(self.reason, restock=self.restock)
        return {"type": "ir.actions.act_window_close"}
