from odoo import api, fields, models
from odoo.tools import float_round

PHARMA_CATEGORY_SELECTION = [
    ("drug_reimbursed", "Médicament remboursable"),
    ("drug_otc", "Médicament non remboursable"),
    ("parapharmacy", "Parapharmacie"),
    ("medical_device", "Dispositif médical (LPP)"),
    ("other", "Autre"),
]

VAT_RATE_SELECTION = [
    ("2.1", "2,1 %"),
    ("5.5", "5,5 %"),
    ("10", "10 %"),
    ("20", "20 %"),
]

# TVA par défaut selon la catégorie (CGI art. 281 octies et 278 bis) :
# médicaments remboursables 2,1 %, non remboursables 10 %, parapharmacie 20 %.
# Certains dispositifs médicaux relèvent du 5,5 % : à ajuster article par article.
DEFAULT_VAT_BY_CATEGORY = {
    "drug_reimbursed": "2.1",
    "drug_otc": "10",
    "parapharmacy": "20",
    "medical_device": "20",
    "other": "20",
}


class ProductTemplate(models.Model):
    _inherit = "product.template"

    pharma_category = fields.Selection(
        PHARMA_CATEGORY_SELECTION, string="Catégorie officine", index=True,
        help="Segmente le chiffre d'affaires et les marges de l'officine.",
    )
    pharma_presentation_id = fields.Many2one(
        "pharma.presentation", string="Présentation BDPM", index=True, copy=False,
    )
    pharma_specialite_id = fields.Many2one(
        related="pharma_presentation_id.specialite_id", store=True,
        string="Spécialité",
    )
    pharma_cip13 = fields.Char(
        related="pharma_presentation_id.cip13", store=True, string="CIP13",
    )
    pharma_cip7 = fields.Char(related="pharma_presentation_id.cip7", string="CIP7")
    pharma_acl13 = fields.Char(
        "Code ACL13 / EAN", index=True,
        help="Code des produits de parapharmacie et dispositifs médicaux.",
    )
    pharma_laboratory_id = fields.Many2one(
        "res.partner", string="Laboratoire", index=True,
        compute="_compute_pharma_laboratory", store=True, readonly=False,
        domain=[("pharma_partner_type", "=", "laboratory")],
    )
    pharma_active_substances = fields.Char(
        related="pharma_specialite_id.active_substances", string="Substances actives",
    )

    # Prix réglementé et remboursement
    pharma_reimbursement_rate = fields.Selection(
        related="pharma_presentation_id.reimbursement_rate",
        store=True, string="Taux de remboursement",
    )
    pharma_public_price = fields.Monetary(
        related="pharma_presentation_id.price_ttc", store=True,
        string="Prix public réglementé TTC",
        currency_field="currency_id",
    )
    pharma_dispensing_fee = fields.Monetary(
        related="pharma_presentation_id.dispensing_fee", string="Honoraire de dispensation",
        currency_field="currency_id",
    )
    pharma_price_regime = fields.Selection(
        [("regulated", "Prix réglementé"), ("free", "Prix libre")],
        string="Régime de prix", compute="_compute_pharma_price_regime", store=True,
        index=True,
    )
    pharma_vat_rate = fields.Selection(
        VAT_RATE_SELECTION, string="TVA officine",
        compute="_compute_pharma_vat_rate", store=True, readonly=False,
    )

    # Génériques et réglementation
    pharma_generic_type = fields.Selection(
        related="pharma_specialite_id.generic_type",
        store=True, string="Type générique",
    )
    pharma_generic_group_id = fields.Many2one(
        related="pharma_specialite_id.generic_group_id", store=True,
        string="Groupe générique",
    )
    pharma_prescription_list = fields.Selection(
        related="pharma_specialite_id.prescription_list",
        store=True, string="Liste",
    )
    pharma_is_narcotic = fields.Boolean(
        "Stupéfiant / assimilé", compute="_compute_pharma_is_narcotic", store=True,
        index=True,
    )
    pharma_availability_status = fields.Selection(
        related="pharma_specialite_id.availability_status",
        store=True, string="Disponibilité nationale",
    )
    pharma_is_mitm = fields.Boolean(
        related="pharma_specialite_id.is_mitm", store=True, string="MITM",
    )

    _pharma_presentation_uniq = models.Constraint(
        "unique (pharma_presentation_id)",
        "Cette présentation BDPM est déjà liée à un autre article.",
    )

    @api.depends("pharma_specialite_id.laboratory_id")
    def _compute_pharma_laboratory(self):
        # Pour un médicament, le laboratoire suit le titulaire de l'AMM ; pour la
        # parapharmacie (sans spécialité), la valeur saisie est conservée.
        for tmpl in self:
            tmpl.pharma_laboratory_id = (
                tmpl.pharma_specialite_id.laboratory_id or tmpl.pharma_laboratory_id
            )

    @api.depends("pharma_category")
    def _compute_pharma_price_regime(self):
        for tmpl in self:
            if not tmpl.pharma_category:
                tmpl.pharma_price_regime = False
            elif tmpl.pharma_category == "drug_reimbursed":
                tmpl.pharma_price_regime = "regulated"
            else:
                tmpl.pharma_price_regime = "free"

    @api.depends("pharma_category")
    def _compute_pharma_vat_rate(self):
        # Valeur par défaut selon la catégorie ; modifiable ensuite (readonly=False).
        for tmpl in self:
            tmpl.pharma_vat_rate = (
                self._pharma_default_vat_rate(tmpl.pharma_category)
                if tmpl.pharma_category else False
            )

    @api.depends("pharma_specialite_id.prescription_list",
                 "pharma_specialite_id.narcotic_rules")
    def _compute_pharma_is_narcotic(self):
        for tmpl in self:
            spec = tmpl.pharma_specialite_id
            tmpl.pharma_is_narcotic = bool(
                spec and (spec.prescription_list == "narcotic" or spec.narcotic_rules)
            )

    @api.onchange("pharma_vat_rate")
    def _onchange_pharma_vat_rate(self):
        if self.pharma_vat_rate:
            vals = self._pharma_prepare_tax_vals(self.pharma_vat_rate)
            self.taxes_id = vals.get("taxes_id", [])
            self.supplier_taxes_id = vals.get("supplier_taxes_id", [])

    # ------------------------------------------------------------------
    # TVA
    # ------------------------------------------------------------------

    @api.model
    def _pharma_default_vat_rate(self, category):
        return DEFAULT_VAT_BY_CATEGORY.get(category, "20")

    @api.model
    def _pharma_find_tax(self, rate, type_tax_use, price_include=None):
        """Cherche la taxe de la société courante correspondant au taux donné.

        Pour les ventes on privilégie une taxe « TTC » (prix taxe incluse), car
        les prix publics des médicaments sont exprimés TTC.
        """
        company = self.env.company
        domain = [
            *self.env["account.tax"]._check_company_domain(company),
            ("type_tax_use", "=", type_tax_use),
            ("amount_type", "=", "percent"),
            ("amount", "=", float(rate)),
            ("tax_scope", "in", [False, "consu"]),
        ]
        # Le plan comptable français livre certaines taxes désactivées (ex. TVA
        # 2,1 % en vente) : on les cherche aussi, puis on active celle retenue.
        taxes = self.env["account.tax"].with_context(active_test=False).search(
            domain, order="active desc, sequence, id"
        )
        if price_include is not None:
            preferred = taxes.filtered(lambda t: t.price_include == price_include)
            taxes = preferred or taxes
        tax = taxes[:1]
        if tax and not tax.active:
            tax.sudo().active = True
        return tax

    @api.model
    def _pharma_prepare_tax_vals(self, rate, price_ttc=None):
        """Taxes de vente/achat et prix de vente pour un taux de TVA donné.

        ``price_ttc`` (prix public TTC) est converti en prix HT si la taxe de
        vente trouvée n'est pas « taxe incluse ».
        """
        vals = {}
        sale_tax = self._pharma_find_tax(rate, "sale", price_include=True)
        purchase_tax = self._pharma_find_tax(rate, "purchase", price_include=False)
        vals["taxes_id"] = [fields.Command.set(sale_tax.ids)]
        vals["supplier_taxes_id"] = [fields.Command.set(purchase_tax.ids)]
        if price_ttc:
            if sale_tax and not sale_tax.price_include:
                vals["list_price"] = float_round(
                    price_ttc / (1 + float(rate) / 100), precision_digits=4
                )
            else:
                vals["list_price"] = price_ttc
        return vals

    def action_pharma_apply_vat(self):
        """Réapplique les taxes correspondant à la TVA officine des articles."""
        for tmpl in self.filtered("pharma_vat_rate"):
            vals = self._pharma_prepare_tax_vals(tmpl.pharma_vat_rate)
            tmpl.write({k: v for k, v in vals.items() if k != "list_price"})
        return True
