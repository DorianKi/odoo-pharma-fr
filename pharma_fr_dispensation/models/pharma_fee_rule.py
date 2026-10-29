from odoo import api, fields, models

FEE_CODE_SELECTION = [
    ("prescription", "Honoraire d'exécution d'ordonnance"),
    ("age", "Honoraire lié à l'âge (moins de 3 ans, 70 ans et plus)"),
    ("complex", "Honoraire d'ordonnance complexe (5 lignes et plus)"),
    ("specific", "Honoraire de dispensation de médicaments spécifiques"),
]


class PharmaFeeRule(models.Model):
    """Barème daté des honoraires de dispensation attachés à l'ordonnance.

    L'honoraire « à la boîte » n'en fait pas partie : il est propre à chaque
    présentation et provient de la BDPM.
    """

    _name = "pharma.fee.rule"
    _description = "Honoraire de dispensation (barème)"
    _order = "code, date_from desc"

    code = fields.Selection(FEE_CODE_SELECTION, string="Honoraire", required=True)
    name = fields.Char("Libellé", required=True)
    amount = fields.Float("Montant TTC", required=True, digits="Product Price")
    reimbursement_rate = fields.Float(
        "Taux de prise en charge AMO (%)", required=True, default=70.0,
        help="Taux appliqué hors exonération (ALD, C2S).",
    )
    date_from = fields.Date("En vigueur à partir du", required=True)
    product_id = fields.Many2one(
        "product.product", string="Article de facturation", required=True,
        domain=[("type", "=", "service")],
    )
    source = fields.Char("Référence")
    active = fields.Boolean(default=True)

    @api.model
    def _get_rule(self, code, on_date):
        return self.search(
            [("code", "=", code), ("date_from", "<=", on_date)],
            order="date_from desc", limit=1,
        )
