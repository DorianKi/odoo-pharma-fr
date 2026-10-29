from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .product_template import GENERIC_TYPES

SCOPE_SELECTION = [
    ("all", "Tous les produits"),
    ("generic", "Génériques"),
    ("princeps", "Remboursables hors génériques"),
    ("drug_otc", "Médicaments non remboursables"),
    ("parapharmacy", "Parapharmacie"),
    ("medical_device", "Dispositifs médicaux"),
]


class PharmaPurchaseAgreement(models.Model):
    """Conditions commerciales négociées avec un fournisseur (grossiste ou
    laboratoire) : remises immédiates (sur facture) et remises différées
    (ristournes de fin d'année, coopération commerciale)."""

    _name = "pharma.purchase.agreement"
    _description = "Conditions commerciales fournisseur"
    _order = "partner_id, date_start desc, id desc"

    name = fields.Char("Intitulé", required=True)
    partner_id = fields.Many2one(
        "res.partner", string="Fournisseur", required=True, index=True,
        domain=[("pharma_partner_type", "in", ("wholesaler", "laboratory"))],
    )
    partner_type = fields.Selection(related="partner_id.pharma_partner_type")
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    date_start = fields.Date("Début", required=True, default=fields.Date.context_today)
    date_end = fields.Date("Fin")
    active = fields.Boolean(default=True)
    line_ids = fields.One2many(
        "pharma.purchase.agreement.line", "agreement_id", string="Conditions", copy=True
    )
    note = fields.Html("Notes")

    @api.constrains("date_start", "date_end")
    def _check_dates(self):
        for agreement in self:
            if agreement.date_end and agreement.date_end < agreement.date_start:
                raise ValidationError("La date de fin doit suivre la date de début.")

    @api.model
    def _find_for(self, partner, date, company):
        """Conditions en vigueur pour un fournisseur à une date donnée."""
        if not partner:
            return self.browse()
        return self.search([
            ("partner_id", "=", partner.commercial_partner_id.id),
            ("company_id", "=", company.id),
            ("date_start", "<=", date),
            "|", ("date_end", "=", False), ("date_end", ">=", date),
        ], order="date_start desc, id desc", limit=1)

    def _find_line(self, product_tmpl, qty):
        """Condition la plus spécifique applicable au produit et à la quantité.

        Priorité : article > laboratoire + segment > laboratoire > segment > tous ;
        à spécificité égale, la remise la plus forte l'emporte.
        """
        self.ensure_one()
        candidates = self.line_ids.filtered(
            lambda line: line._matches(product_tmpl) and qty >= line.min_qty
        )
        if not candidates:
            return candidates
        return max(candidates, key=lambda line: (line._specificity(), line.discount, line.id))


class PharmaPurchaseAgreementLine(models.Model):
    _name = "pharma.purchase.agreement.line"
    _description = "Ligne de conditions commerciales"
    _order = "agreement_id, sequence, id"

    agreement_id = fields.Many2one(
        "pharma.purchase.agreement", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(default=10)
    scope = fields.Selection(SCOPE_SELECTION, string="Segment", required=True, default="all")
    laboratory_id = fields.Many2one(
        "res.partner", string="Laboratoire",
        domain=[("pharma_partner_type", "=", "laboratory")],
    )
    product_tmpl_id = fields.Many2one("product.template", string="Article")
    min_qty = fields.Float("Quantité minimum", default=0.0)
    discount = fields.Float("Remise immédiate (%)", digits="Discount")
    deferred_rebate = fields.Float(
        "Remise différée (%)", digits="Discount",
        help="Ristourne de fin d'année, coopération commerciale... versée hors facture.",
    )

    _discount_check = models.Constraint(
        "CHECK (discount >= 0 AND discount <= 100 AND deferred_rebate >= 0 "
        "AND deferred_rebate <= 100)",
        "Les remises doivent être comprises entre 0 et 100 %.",
    )

    def _specificity(self):
        self.ensure_one()
        if self.product_tmpl_id:
            return 4
        if self.laboratory_id and self.scope != "all":
            return 3
        if self.laboratory_id:
            return 2
        return 1 if self.scope != "all" else 0

    def _matches(self, product_tmpl):
        self.ensure_one()
        if self.product_tmpl_id:
            return self.product_tmpl_id == product_tmpl
        if self.laboratory_id and self.laboratory_id != product_tmpl.pharma_laboratory_id:
            return False
        return self._scope_matches(product_tmpl)

    def _scope_matches(self, product_tmpl):
        scope = self.scope
        if scope == "all":
            return True
        if scope == "generic":
            return product_tmpl.pharma_generic_type in GENERIC_TYPES
        if scope == "princeps":
            return (
                product_tmpl.pharma_category == "drug_reimbursed"
                and product_tmpl.pharma_generic_type not in GENERIC_TYPES
            )
        return product_tmpl.pharma_category == scope
