from odoo import api, fields, models


class PharmaInventoryGap(models.Model):
    """Écart d'inventaire constaté (démarque connue ou inconnue)."""

    _name = "pharma.inventory.gap"
    _description = "Écart d'inventaire"
    _order = "date desc, id desc"

    date = fields.Datetime("Date", required=True, default=fields.Datetime.now, index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    product_id = fields.Many2one("product.product", "Article", required=True, index=True)
    pharma_category = fields.Selection(related="product_id.pharma_category", store=True)
    lot_id = fields.Many2one("stock.lot", "Lot")
    location_id = fields.Many2one("stock.location", "Emplacement")
    theoretical_qty = fields.Float("Stock théorique")
    counted_qty = fields.Float("Stock compté")
    gap_qty = fields.Float("Écart (unités)")
    unit_cost = fields.Float("Coût unitaire", digits="Product Price")
    gap_value = fields.Monetary("Écart (valeur)")
    reason = fields.Selection(
        [("cycle_count", "Inventaire tournant"), ("annual", "Inventaire annuel"),
         ("correction", "Correction")],
        string="Contexte", default="cycle_count", required=True,
    )
    user_id = fields.Many2one("res.users", "Compté par", default=lambda self: self.env.user)

    @api.model
    def _record_from_quants(self, quants):
        vals_list = []
        reason = self.env.context.get("pharma_gap_reason", "cycle_count")
        for quant in quants:
            gap = quant.inventory_quantity - quant.quantity
            if not quant.product_id.pharma_category or abs(gap) < 1e-6:
                continue
            cost = quant.product_id.with_company(quant.company_id).standard_price
            vals_list.append({
                "company_id": quant.company_id.id,
                "product_id": quant.product_id.id,
                "lot_id": quant.lot_id.id,
                "location_id": quant.location_id.id,
                "theoretical_qty": quant.quantity,
                "counted_qty": quant.inventory_quantity,
                "gap_qty": gap,
                "unit_cost": cost,
                "gap_value": gap * cost,
                "reason": reason,
            })
        return self.sudo().create(vals_list)


class StockQuant(models.Model):
    _inherit = "stock.quant"

    def _apply_inventory(self, date=None):
        if not self.env.context.get("pharma_skip_gap"):
            self.env["pharma.inventory.gap"]._record_from_quants(
                self.filtered(lambda q: q.location_id.usage == "internal")
            )
        return super()._apply_inventory(date=date)
