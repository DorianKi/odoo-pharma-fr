from odoo import api, fields, models
from odoo.tools import float_compare


def _cap_advantages(discount, rebate, cap):
    """Plafonne une remise immédiate et une remise différée pour que l'avantage
    total ``1 - (1 - d)(1 - r)`` n'excède pas ``cap`` (tous en %).

    La remise immédiate est servie en priorité. Renvoie (d, r, plafonné).

    >>> _cap_advantages(50, 0, 40)
    (40, 0.0, True)
    >>> _cap_advantages(30, 20, 40)[1]
    14.2857
    >>> _cap_advantages(10, 5, None)
    (10, 5, False)
    """
    if cap is None:
        return discount, rebate, False
    capped = False
    if discount > cap:
        discount, capped = cap, True
    if discount >= 100:
        max_rebate = 0.0
    else:
        max_rebate = max(0.0, (1 - (1 - cap / 100) / (1 - discount / 100)) * 100)
    max_rebate = round(max_rebate, 4)
    if rebate > max_rebate:
        rebate, capped = max_rebate, True
    return discount, rebate, capped


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    pharma_agreement_line_id = fields.Many2one(
        "pharma.purchase.agreement.line", string="Condition commerciale",
        compute="_compute_pharma_agreement", store=True,
    )
    pharma_deferred_rebate = fields.Float(
        "Remise différée (%)", digits="Discount",
        compute="_compute_pharma_agreement", store=True, readonly=False,
    )
    pharma_has_cap = fields.Boolean(
        "Remise plafonnée par la loi", compute="_compute_pharma_agreement", store=True,
    )
    pharma_cap_rate = fields.Float(
        "Plafond légal (%)", digits="Discount", compute="_compute_pharma_agreement", store=True,
    )
    pharma_discount_capped = fields.Boolean(
        "Remise ramenée au plafond", compute="_compute_pharma_agreement", store=True,
        help="La condition négociée dépassait le plafond légal et a été réduite.",
    )
    pharma_total_advantage = fields.Float(
        "Avantage total (%)", digits="Discount", compute="_compute_pharma_net", store=True,
        help="Remise immédiate et remise différée cumulées.",
    )
    pharma_over_cap = fields.Boolean(
        "Au-delà du plafond légal", compute="_compute_pharma_net", store=True,
    )
    pharma_net_price_unit = fields.Monetary(
        "Prix net net unitaire", compute="_compute_pharma_net", store=True,
        currency_field="currency_id",
        help="Prix unitaire après remise immédiate et remise différée : coût réel "
             "d'achat pour le calcul de la marge.",
    )

    def _pharma_order_date(self):
        self.ensure_one()
        date = self.order_id.date_order or fields.Datetime.now()
        return fields.Date.to_date(date)

    def _pharma_discount_values(self):
        """Remises applicables à la ligne selon les conditions commerciales du
        fournisseur et le plafond légal en vigueur."""
        self.ensure_one()
        date = self._pharma_order_date()
        tmpl = self.product_id.product_tmpl_id
        agreement = self.env["pharma.purchase.agreement"]._find_for(
            self.order_id.partner_id, date, self.company_id or self.env.company
        )
        agreement_line = (
            agreement._find_line(tmpl, self.product_qty) if agreement else agreement.line_ids
        )
        if agreement_line:
            discount, rebate = agreement_line.discount, agreement_line.deferred_rebate
        else:
            discount, rebate = self.discount, 0.0
        cap = self.env["pharma.discount.cap"]._get_rate(tmpl.pharma_discount_cap_category, date)
        discount, rebate, capped = _cap_advantages(discount, rebate, cap)
        return {
            "agreement_line": agreement_line,
            "discount": discount,
            "deferred_rebate": rebate,
            "cap": cap,
            "capped": capped,
        }

    @api.depends(
        "product_id", "product_qty", "order_id.partner_id", "order_id.date_order",
        "product_id.pharma_discount_cap_category",
    )
    def _compute_pharma_agreement(self):
        for line in self:
            if not line.product_id or line.display_type:
                line.pharma_agreement_line_id = False
                line.pharma_deferred_rebate = 0.0
                line.pharma_has_cap = False
                line.pharma_cap_rate = 0.0
                line.pharma_discount_capped = False
                continue
            values = line._pharma_discount_values()
            line.pharma_agreement_line_id = values["agreement_line"]
            line.pharma_deferred_rebate = values["deferred_rebate"]
            line.pharma_has_cap = values["cap"] is not None
            line.pharma_cap_rate = values["cap"] or 0.0
            line.pharma_discount_capped = values["capped"]

    @api.depends("price_unit", "discount", "pharma_deferred_rebate", "pharma_has_cap",
                 "pharma_cap_rate")
    def _compute_pharma_net(self):
        for line in self:
            remaining = (1 - (line.discount or 0) / 100) * (1 - line.pharma_deferred_rebate / 100)
            line.pharma_total_advantage = round((1 - remaining) * 100, 4)
            line.pharma_net_price_unit = line.price_unit * remaining
            line.pharma_over_cap = line.pharma_has_cap and float_compare(
                line.pharma_total_advantage, line.pharma_cap_rate, precision_digits=2
            ) > 0

    def _compute_price_unit_and_date_planned_and_name(self):
        """Après le calcul standard (prix et remise du tarif fournisseur), applique
        la remise des conditions commerciales, plafonnée par la loi."""
        super()._compute_price_unit_and_date_planned_and_name()
        for line in self:
            if (
                not line.product_id
                or line.invoice_lines
                or not line.company_id
                or line.technical_price_unit != line.price_unit
            ):
                continue
            line.discount = line._pharma_discount_values()["discount"]

    @api.model_create_multi
    def create(self, vals_list):
        # À la création, la remise calculée en pré-calcul n'est pas conservée par
        # l'ORM (seul le prix l'est) : on l'applique ici, sauf remise saisie.
        lines = super().create(vals_list)
        for line, vals in zip(lines, vals_list, strict=True):
            if (
                "discount" not in vals
                and line.product_id
                and not line.display_type
                and line.technical_price_unit == line.price_unit
            ):
                line.discount = line._pharma_discount_values()["discount"]
        return lines

    def _pharma_apply_agreement(self):
        for line in self.filtered(lambda pol: pol.product_id and not pol.invoice_lines):
            values = line._pharma_discount_values()
            line.write({
                "discount": values["discount"],
                "pharma_deferred_rebate": values["deferred_rebate"],
            })
