from odoo import api, fields, models

ORDER_TYPE_SELECTION = [
    ("wholesaler", "Commande grossiste"),
    ("direct", "Commande directe laboratoire"),
    ("other", "Autre fournisseur"),
]


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    pharma_order_type = fields.Selection(
        ORDER_TYPE_SELECTION, string="Type de commande",
        compute="_compute_pharma_order_type", store=True, readonly=False, index=True,
    )
    pharma_agreement_id = fields.Many2one(
        "pharma.purchase.agreement", string="Conditions commerciales",
        compute="_compute_pharma_agreement_id",
    )
    pharma_franco_amount = fields.Monetary(
        "Franco", compute="_compute_pharma_franco", currency_field="currency_id",
    )
    pharma_below_franco = fields.Boolean(
        "Sous le franco", compute="_compute_pharma_franco",
    )
    pharma_franco_missing = fields.Monetary(
        "Montant manquant pour le franco", compute="_compute_pharma_franco",
        currency_field="currency_id",
    )
    pharma_deferred_rebate_amount = fields.Monetary(
        "Remises différées attendues", compute="_compute_pharma_deferred_rebate",
        store=True, currency_field="currency_id",
    )
    pharma_has_over_cap = fields.Boolean(
        "Remise au-delà du plafond légal", compute="_compute_pharma_has_over_cap",
    )

    @api.depends("partner_id")
    def _compute_pharma_order_type(self):
        mapping = {"wholesaler": "wholesaler", "laboratory": "direct"}
        for order in self:
            partner_type = order.partner_id.commercial_partner_id.pharma_partner_type
            order.pharma_order_type = mapping.get(partner_type, "other")

    @api.depends("partner_id", "date_order", "company_id")
    def _compute_pharma_agreement_id(self):
        Agreement = self.env["pharma.purchase.agreement"]
        for order in self:
            order.pharma_agreement_id = Agreement._find_for(
                order.partner_id,
                fields.Date.to_date(order.date_order or fields.Datetime.now()),
                order.company_id or self.env.company,
            )

    @api.depends("partner_id", "amount_untaxed", "state")
    def _compute_pharma_franco(self):
        for order in self:
            franco = order.partner_id.commercial_partner_id.pharma_franco_amount
            order.pharma_franco_amount = franco
            missing = franco - order.amount_untaxed if franco else 0.0
            order.pharma_below_franco = (
                order.state in ("draft", "sent") and bool(order.order_line) and missing > 0
            )
            order.pharma_franco_missing = max(missing, 0.0)

    @api.depends("order_line.price_subtotal", "order_line.pharma_deferred_rebate")
    def _compute_pharma_deferred_rebate(self):
        for order in self:
            order.pharma_deferred_rebate_amount = sum(
                line.price_subtotal * line.pharma_deferred_rebate / 100
                for line in order.order_line
            )

    @api.depends("order_line.pharma_over_cap")
    def _compute_pharma_has_over_cap(self):
        for order in self:
            order.pharma_has_over_cap = any(order.order_line.mapped("pharma_over_cap"))

    def action_pharma_apply_agreement(self):
        """Réapplique les conditions commerciales (et le plafond légal) aux lignes."""
        self.order_line._pharma_apply_agreement()
        return True
