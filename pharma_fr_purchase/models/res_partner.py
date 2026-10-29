from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    pharma_franco_amount = fields.Monetary(
        "Franco de port (HT)",
        currency_field="pharma_currency_id",
        help="Montant HT minimum de commande pour être livré sans frais.",
    )
    pharma_currency_id = fields.Many2one(
        "res.currency", compute="_compute_pharma_currency_id"
    )
    pharma_is_main_wholesaler = fields.Boolean(
        "Grossiste principal",
        help="Grossiste-répartiteur de référence de l'officine (fournisseur par "
             "défaut du réassort).",
    )
    pharma_deliveries_per_day = fields.Integer(
        "Livraisons par jour", default=0,
        help="Nombre de tournées de livraison quotidiennes (grossiste-répartiteur).",
    )
    pharma_agreement_ids = fields.One2many(
        "pharma.purchase.agreement", "partner_id", string="Conditions commerciales"
    )

    def _compute_pharma_currency_id(self):
        for partner in self:
            partner.pharma_currency_id = (
                partner.company_id.currency_id or self.env.company.currency_id
            )
