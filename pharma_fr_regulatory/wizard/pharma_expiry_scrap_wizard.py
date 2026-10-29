from odoo import Command, api, fields, models
from odoo.exceptions import UserError


class PharmaExpiryScrapWizard(models.TransientModel):
    """Destruction des lots périmés (ou périmant avant une date donnée)."""

    _name = "pharma.expiry.scrap.wizard"
    _description = "Destruction des périmés"

    limit_date = fields.Datetime(
        "Périmés avant le", required=True, default=fields.Datetime.now,
    )
    quant_ids = fields.Many2many("stock.quant", string="Stocks concernés")
    result = fields.Text(readonly=True)
    state = fields.Selection([("draft", "Sélection"), ("done", "Terminé")], default="draft")

    @api.model
    def _expired_quants(self, limit_date):
        return self.env["stock.quant"].search([
            ("location_id.usage", "=", "internal"),
            ("company_id", "=", self.env.company.id),
            ("expiration_date", "!=", False),
            ("expiration_date", "<", limit_date),
            ("quantity", ">", 0),
        ])

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if self.env.context.get("active_model") == "stock.quant":
            quant_ids = self.env.context.get("active_ids", [])
        else:
            limit = values.get("limit_date") or fields.Datetime.now()
            quant_ids = self._expired_quants(limit).ids
        values["quant_ids"] = [Command.set(quant_ids)]
        return values

    @api.onchange("limit_date")
    def _onchange_limit_date(self):
        self.quant_ids = self._expired_quants(self.limit_date)

    def action_scrap(self):
        self.ensure_one()
        quants = self.quant_ids.filtered(lambda q: q.quantity > 0)
        if not quants:
            raise UserError("Aucun stock à détruire.")
        tag = self.env.ref("pharma_fr_regulatory.scrap_reason_expired")
        scraps = self.env["stock.scrap"].create([
            {
                "product_id": quant.product_id.id,
                "lot_id": quant.lot_id.id,
                "scrap_qty": quant.quantity,
                "location_id": quant.location_id.id,
                "company_id": quant.company_id.id,
                "origin": "Destruction des périmés",
                "scrap_reason_tag_ids": [Command.set(tag.ids)],
            }
            for quant in quants
        ])
        value = sum(s.scrap_qty * s.product_id.standard_price for s in scraps)
        scraps.do_scrap()
        self.write({
            "state": "done",
            "result": (
                f"Lots détruits : {len(scraps)}\n"
                f"Unités : {sum(scraps.mapped('scrap_qty')):g}\n"
                f"Valeur au coût d'achat : {value:.2f} {self.env.company.currency_id.symbol}"
            ),
        })
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
