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
    prescriber_id = fields.Many2one("res.partner", "Prescripteur")
    prescription_id = fields.Many2one("pharma.prescription", "Ordonnance")
    state = fields.Selection(
        [("open", "À rendre"), ("delivered", "Rendu"), ("cancelled", "Abandonné"),
         ("closed", "Sans suite")],
        string="Suivi", compute="_compute_state", store=True, readonly=False, index=True,
        help="« À rendre » : produit promis au patient, en attente de délivrance.",
    )
    delivered_date = fields.Datetime("Date de délivrance", copy=False)
    delivered_prescription_id = fields.Many2one(
        "pharma.prescription", "Délivrance du promis", copy=False,
    )
    delay_days = fields.Float(
        "Délai (jours)", compute="_compute_delay_days", store=True, digits=(12, 1),
        help="Délai entre la demande et la délivrance du produit promis.",
    )
    unit_price = fields.Monetary("Prix unitaire TTC")
    amount_lost = fields.Monetary(
        "Montant non servi TTC", compute="_compute_amount_lost", store=True
    )

    @api.depends("outcome")
    def _compute_state(self):
        # Recalculé seulement quand l'issue change : un promis rendu reste « Rendu ».
        for item in self:
            item.state = "open" if item.outcome == "deferred" else "closed"

    @api.depends("date", "delivered_date")
    def _compute_delay_days(self):
        for item in self:
            if item.delivered_date and item.date:
                item.delay_days = (item.delivered_date - item.date).total_seconds() / 86400
            else:
                item.delay_days = 0.0

    def action_mark_delivered(self, prescription=None):
        """Marque les promis comme rendus (optionnellement liés à la délivrance)."""
        self.filtered(lambda i: i.state == "open").write({
            "state": "delivered",
            "delivered_date": fields.Datetime.now(),
            "delivered_prescription_id": prescription.id if prescription else False,
        })
        return True

    def action_cancel(self):
        self.filtered(lambda i: i.state == "open").state = "cancelled"
        return True

    @api.depends("quantity", "unit_price")
    def _compute_amount_lost(self):
        for item in self:
            item.amount_lost = item.quantity * item.unit_price
