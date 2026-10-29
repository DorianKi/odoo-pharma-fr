from odoo import api, fields, models


class PharmaMissingItem(models.Model):
    """Manquant : demande qui n'a pas pu être servie (vente perdue ou différée).

    Indicateur clé de la gestion du stock : taux de service, chiffre d'affaires
    perdu, produits en rupture chez le fournisseur ou mal réapprovisionnés.
    """

    _name = "pharma.missing.item"
    _description = "Manquant (demande non servie)"
    _order = "date desc, id desc"

    date = fields.Datetime("Date", required=True, default=fields.Datetime.now, index=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    product_id = fields.Many2one("product.product", "Article", required=True, index=True)
    product_tmpl_id = fields.Many2one(related="product_id.product_tmpl_id", store=True)
    pharma_category = fields.Selection(related="product_tmpl_id.pharma_category", store=True)
    quantity = fields.Float("Quantité manquante", required=True, default=1.0)
    reason = fields.Selection(
        [
            ("stock", "Stock insuffisant à l'officine"),
            ("national_shortage", "Rupture ou tension nationale"),
            ("supplier", "Indisponible chez le fournisseur"),
        ],
        string="Motif", required=True, default="stock", index=True,
    )
    outcome = fields.Selection(
        [
            ("lost", "Vente perdue"),
            ("deferred", "Délivrance différée (à rendre)"),
            ("substituted", "Remplacé par un équivalent"),
        ],
        string="Issue", required=True, default="lost",
    )
    patient_id = fields.Many2one("res.partner", "Patient")
    prescription_id = fields.Many2one("pharma.prescription", "Ordonnance")
    unit_price = fields.Monetary("Prix unitaire TTC")
    amount_lost = fields.Monetary(
        "Montant non servi TTC", compute="_compute_amount_lost", store=True
    )

    @api.depends("quantity", "unit_price")
    def _compute_amount_lost(self):
        for item in self:
            item.amount_lost = item.quantity * item.unit_price
