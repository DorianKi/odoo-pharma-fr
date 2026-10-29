import re

from odoo import api, fields, models
from odoo.tools import float_round

GENERIC_TYPES = ("generic", "generic_posology", "generic_substitutable")


def split_amounts(qty, price, fee, base, rate, exempt, amc_coverage, tiers_payant):
    """Répartit le montant d'une ligne entre AMO, AMC et patient.

    :param qty: nombre de boîtes
    :param price: prix public TTC unitaire (hors honoraire)
    :param fee: honoraire de dispensation unitaire (à la boîte)
    :param base: base de remboursement unitaire (prix ou base générique)
    :param rate: taux de remboursement AMO (0, 15, 30, 65, 100)
    :param exempt: exonération du ticket modérateur (ALD, C2S) : AMO à 100 %
    :param amc_coverage: 'none', 'tm' ou 'tm_except_15'
    :param tiers_payant: dispense d'avance de frais ; sinon le patient règle tout
    :return: (total, amo, amc, patient)

    >>> split_amounts(2, 2.18, 1.02, 2.18, 65, False, "tm", True)
    (6.4, 4.16, 2.24, 0.0)
    >>> split_amounts(1, 10.0, 1.02, 8.0, 65, False, "none", True)
    (11.02, 5.86, 0.0, 5.16)
    >>> split_amounts(1, 5.0, 0.0, 5.0, 0, False, "tm", True)
    (5.0, 0.0, 0.0, 5.0)
    """
    total = float_round(qty * (price + fee), precision_digits=2)
    if not rate or not tiers_payant:
        return total, 0.0, 0.0, total
    effective = 100 if exempt else rate
    covered = qty * (base + fee)
    amo = float_round(covered * effective / 100, precision_digits=2)
    amc = 0.0
    if amc_coverage == "tm" or (amc_coverage == "tm_except_15" and rate != 15):
        amc = float_round(covered - amo, precision_digits=2)
    patient = float_round(total - amo - amc, precision_digits=2)
    return total, amo, amc, patient


def unit_count(label):
    """Nombre d'unités d'une présentation d'après son libellé BDPM.

    >>> unit_count("plaquette(s) PVC aluminium de 8 comprimé(s)")
    8
    >>> unit_count("flacon de 100 ml") is None
    True
    """
    match = re.search(r"\bde (\d+) (?:comprim|g[ée]lule|capsule|sachet|suppositoire|ampoule|dose)",
                      label or "", re.IGNORECASE)
    return int(match.group(1)) if match else None


class PharmaPrescriptionLine(models.Model):
    _name = "pharma.prescription.line"
    _description = "Ligne d'ordonnance dispensée"
    _order = "prescription_id, sequence, id"

    prescription_id = fields.Many2one(
        "pharma.prescription", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related="prescription_id.company_id", store=True)
    currency_id = fields.Many2one(related="prescription_id.currency_id")
    state = fields.Selection(related="prescription_id.state", store=True)
    dispensing_date = fields.Datetime(related="prescription_id.dispensing_date", store=True)
    patient_id = fields.Many2one(related="prescription_id.patient_id", store=True)

    product_id = fields.Many2one(
        "product.product", string="Article délivré", required=True,
        domain=[("pharma_category", "!=", False)],
    )
    product_tmpl_id = fields.Many2one(related="product_id.product_tmpl_id", store=True)
    prescribed_product_id = fields.Many2one(
        "product.product", string="Article prescrit",
        help="Renseigné en cas de substitution (princeps prescrit, générique délivré).",
    )
    quantity = fields.Integer("Boîtes", default=1, required=True)
    ald_related = fields.Boolean(
        "En rapport avec l'ALD", help="Partie haute de l'ordonnance bizone."
    )
    non_substitutable = fields.Boolean(
        "Non substituable", help="Mention « non substituable » du prescripteur."
    )
    substitution_refused = fields.Boolean(
        "Refus de substitution",
        help="Le patient refuse le générique : remboursement sur la base du générique "
             "et pas de tiers payant.",
    )
    is_substitution = fields.Boolean(
        "Substitution générique", compute="_compute_is_substitution", store=True,
    )
    is_generic = fields.Boolean(compute="_compute_is_substitution", store=True)

    reimbursement_rate = fields.Integer(
        "Taux AMO (%)", compute="_compute_prices", store=True,
    )
    unit_price = fields.Monetary(
        "Prix unitaire TTC", compute="_compute_prices", store=True, readonly=False,
    )
    box_fee = fields.Monetary(
        "Honoraire à la boîte", compute="_compute_prices", store=True,
    )
    base_unit = fields.Monetary(
        "Base de remboursement unitaire", compute="_compute_prices", store=True,
    )
    vat_rate = fields.Float("TVA (%)", compute="_compute_prices", store=True)

    tiers_payant = fields.Boolean("Tiers payant appliqué", compute="_compute_amounts", store=True)
    amount_total = fields.Monetary("Total TTC", compute="_compute_amounts", store=True)
    amount_amo = fields.Monetary("Part AMO", compute="_compute_amounts", store=True)
    amount_amc = fields.Monetary("Part AMC", compute="_compute_amounts", store=True)
    amount_patient = fields.Monetary("Part patient", compute="_compute_amounts", store=True)
    amount_untaxed = fields.Monetary("Total HT", compute="_compute_amounts", store=True)
    amount_fees_untaxed = fields.Monetary(
        "Honoraires HT", compute="_compute_amounts", store=True,
    )

    unit_cost = fields.Float(
        "Coût unitaire", digits="Product Price", copy=False,
        help="Coût d'achat de l'article au moment de la délivrance.",
    )
    amount_cost = fields.Monetary("Coût d'achat", compute="_compute_margin", store=True)
    margin = fields.Monetary("Marge brute HT", compute="_compute_margin", store=True)
    lot_names = fields.Char("Lots délivrés", copy=False)

    _quantity_check = models.Constraint(
        "CHECK (quantity > 0)", "La quantité délivrée doit être positive."
    )

    @api.depends("product_id", "prescribed_product_id")
    def _compute_is_substitution(self):
        for line in self:
            tmpl = line.product_id.product_tmpl_id
            line.is_generic = tmpl.pharma_generic_type in GENERIC_TYPES
            prescribed = line.prescribed_product_id.product_tmpl_id
            line.is_substitution = bool(
                prescribed
                and prescribed != tmpl
                and line.is_generic
                and prescribed.pharma_generic_group_id
                and prescribed.pharma_generic_group_id == tmpl.pharma_generic_group_id
            )

    @api.depends("product_id", "substitution_refused", "non_substitutable")
    def _compute_prices(self):
        for line in self:
            tmpl = line.product_id.product_tmpl_id
            rate = int(tmpl.pharma_reimbursement_rate or 0)
            price = line._pharma_price_ttc()
            line.reimbursement_rate = rate
            line.unit_price = price
            line.box_fee = tmpl.pharma_dispensing_fee if rate else 0.0
            line.base_unit = line._pharma_base_unit(price)
            line.vat_rate = float(tmpl.pharma_vat_rate or 0)

    def _pharma_price_ttc(self):
        """Prix public TTC : prix réglementé BDPM, sinon prix de vente taxes incluses."""
        self.ensure_one()
        tmpl = self.product_id.product_tmpl_id
        if tmpl.pharma_public_price:
            return tmpl.pharma_public_price
        taxes = self.product_id.taxes_id.filtered(
            lambda t: t.company_id == (self.company_id or self.env.company)
        )
        if not taxes:
            return self.product_id.lst_price
        return taxes.compute_all(self.product_id.lst_price, product=self.product_id)["total_included"]

    def _pharma_base_unit(self, price):
        """Base de remboursement : prix public, ou prix du générique le plus cher du
        groupe à conditionnement identique en cas de refus de substitution."""
        self.ensure_one()
        tmpl = self.product_id.product_tmpl_id
        if (
            not self.substitution_refused
            or self.non_substitutable
            or tmpl.pharma_generic_type != "princeps"
            or not tmpl.pharma_generic_group_id
        ):
            return price
        count = unit_count(tmpl.pharma_presentation_id.name)
        generics = self.env["pharma.presentation"].search([
            ("generic_group_id", "=", tmpl.pharma_generic_group_id.id),
            ("generic_type", "in", GENERIC_TYPES),
            ("is_marketed", "=", True),
            ("price_ttc", ">", 0),
        ])
        if count:
            generics = generics.filtered(lambda p: unit_count(p.name) == count)
        if not generics:
            return price
        return min(price, max(generics.mapped("price_ttc")))

    @api.depends(
        "quantity", "unit_price", "box_fee", "base_unit", "reimbursement_rate", "vat_rate",
        "ald_related", "substitution_refused", "non_substitutable",
        "prescription_id.patient_id.pharma_exemption",
        "prescription_id.patient_id.pharma_amc_coverage",
        "prescription_id.patient_id.pharma_tiers_payant",
        "prescription_id.patient_id.pharma_amc_id",
    )
    def _compute_amounts(self):
        for line in self:
            patient = line.prescription_id.patient_id
            exempt = patient.pharma_exemption == "c2s" or (
                patient.pharma_exemption == "ald" and line.ald_related
            )
            amc_coverage = patient.pharma_amc_coverage if patient.pharma_amc_id else "none"
            refused = line.substitution_refused and not line.non_substitutable
            tiers_payant = bool(patient.pharma_tiers_payant) and not refused
            total, amo, amc, rest = split_amounts(
                line.quantity, line.unit_price, line.box_fee, line.base_unit,
                line.reimbursement_rate, exempt, amc_coverage, tiers_payant,
            )
            line.tiers_payant = tiers_payant and bool(line.reimbursement_rate)
            line.amount_total = total
            line.amount_amo = amo
            line.amount_amc = amc
            line.amount_patient = rest
            factor = 1 + line.vat_rate / 100
            line.amount_untaxed = float_round(total / factor, precision_digits=2)
            line.amount_fees_untaxed = float_round(
                line.quantity * line.box_fee / factor, precision_digits=2
            )

    @api.depends("unit_cost", "quantity", "amount_untaxed")
    def _compute_margin(self):
        for line in self:
            line.amount_cost = line.unit_cost * line.quantity
            line.margin = line.amount_untaxed - line.amount_cost

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if not self.env.context.get("pharma_skip_fees"):
            lines.prescription_id._pharma_recompute_fees()
        return lines

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("pharma_skip_fees") and {
            "product_id", "quantity", "ald_related", "substitution_refused", "non_substitutable"
        } & set(vals):
            self.prescription_id._pharma_recompute_fees()
        return result

    def unlink(self):
        prescriptions = self.prescription_id
        result = super().unlink()
        prescriptions.exists()._pharma_recompute_fees()
        return result
