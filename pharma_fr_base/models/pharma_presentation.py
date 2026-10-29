from odoo import api, fields, models
from odoo.exceptions import UserError

REIMBURSEMENT_RATE_SELECTION = [
    ("0", "Non remboursable"),
    ("15", "15 %"),
    ("30", "30 %"),
    ("65", "65 %"),
    ("100", "100 %"),
]


class PharmaPresentation(models.Model):
    """Présentation (boîte) d'une spécialité, identifiée par son CIP13.

    C'est le référentiel « base médicament » : toutes les présentations de la
    BDPM y figurent. Seules celles que l'officine référence deviennent des
    articles (product.template), via :meth:`action_create_products`.
    """

    _name = "pharma.presentation"
    _description = "Présentation de médicament (CIP)"
    _order = "specialite_id, cip13"
    _rec_names_search = ["cip13", "cip7", "specialite_id", "name"]

    cip13 = fields.Char("Code CIP13", required=True, index=True, size=13)
    cip7 = fields.Char("Code CIP7", index=True, size=7)
    name = fields.Char("Libellé de la présentation", required=True)
    specialite_id = fields.Many2one(
        "pharma.specialite", required=True, ondelete="cascade", index=True
    )
    admin_status = fields.Char("Statut administratif")
    marketing_status = fields.Char("État de commercialisation")
    marketing_date = fields.Date("Date de déclaration de commercialisation")
    is_marketed = fields.Boolean(
        "Commercialisée", compute="_compute_is_marketed", store=True, index=True
    )
    community_approval = fields.Selection(
        [("oui", "Oui"), ("non", "Non"), ("unknown", "Inconnu")],
        string="Agrément collectivités",
        default="unknown",
    )

    # Prix et remboursement
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.ref("base.EUR"), required=True
    )
    reimbursement_rate = fields.Selection(
        REIMBURSEMENT_RATE_SELECTION, string="Taux de remboursement", default="0",
        required=True, index=True,
    )
    reimbursement_rates_raw = fields.Char("Taux (BDPM brut)")
    reimbursement_indications = fields.Text("Indications ouvrant droit au remboursement")
    price_ttc = fields.Monetary(
        "Prix public TTC (hors honoraires)",
        help="Prix réglementé du médicament, hors honoraires de dispensation.",
    )
    price_with_fees = fields.Monetary("Prix public TTC honoraires inclus")
    dispensing_fee = fields.Monetary("Honoraire de dispensation (boîte)")
    is_reimbursable = fields.Boolean(
        compute="_compute_is_reimbursable", store=True, string="Remboursable"
    )

    # Rappels de la spécialité (pour filtrer / regrouper)
    laboratory_id = fields.Many2one(related="specialite_id.laboratory_id", store=True)
    generic_type = fields.Selection(
        related="specialite_id.generic_type", store=True
    )
    generic_group_id = fields.Many2one(
        related="specialite_id.generic_group_id", store=True
    )
    prescription_list = fields.Selection(
        related="specialite_id.prescription_list",
        store=True,
    )
    availability_status = fields.Selection(
        related="specialite_id.availability_status",
        store=True,
    )

    product_tmpl_id = fields.Many2one(
        "product.template", string="Article officine", index=True, copy=False,
        ondelete="set null",
    )
    is_referenced = fields.Boolean(
        "Référencé", compute="_compute_is_referenced", store=True,
        help="La présentation est référencée comme article de l'officine.",
    )

    _cip13_uniq = models.Constraint(
        "unique (cip13)", "Ce code CIP13 existe déjà."
    )

    @api.depends("marketing_status")
    def _compute_is_marketed(self):
        for pres in self:
            status = (pres.marketing_status or "").lower()
            pres.is_marketed = "commercialisation" in status and "arr" not in status

    @api.depends("reimbursement_rate")
    def _compute_is_reimbursable(self):
        for pres in self:
            pres.is_reimbursable = pres.reimbursement_rate != "0"

    @api.depends("product_tmpl_id")
    def _compute_is_referenced(self):
        for pres in self:
            pres.is_referenced = bool(pres.product_tmpl_id)

    @api.depends("cip13", "specialite_id.name", "name")
    def _compute_display_name(self):
        for pres in self:
            pres.display_name = f"[{pres.cip13}] {pres._get_product_name()}"

    # ------------------------------------------------------------------
    # Création des articles
    # ------------------------------------------------------------------

    def _get_product_name(self):
        self.ensure_one()
        spec_name = self.specialite_id.name or ""
        return f"{spec_name} - {self.name}" if self.name else spec_name

    def _prepare_product_vals(self):
        """Valeurs de l'article créé pour cette présentation."""
        self.ensure_one()
        category = "drug_reimbursed" if self.is_reimbursable else "drug_otc"
        vals = {
            "name": self._get_product_name(),
            "type": "consu",
            "is_storable": True,
            "tracking": "lot",
            "use_expiration_date": True,
            "barcode": self.cip13,
            "default_code": self.cip13,
            "pharma_category": category,
            "pharma_presentation_id": self.id,
            "sale_ok": True,
            "purchase_ok": True,
        }
        templates = self.env["product.template"]
        vat_rate = templates._pharma_default_vat_rate(category)
        vals["pharma_vat_rate"] = vat_rate
        vals.update(templates._pharma_prepare_tax_vals(vat_rate, self.price_ttc))
        return vals

    def _create_products(self):
        """Crée (ou relie) les articles des présentations, sans doublon.

        Si un article portant déjà le code-barres CIP13 existe, il est relié
        à la présentation au lieu d'en créer un nouveau.
        """
        to_process = self.filtered(lambda p: not p.product_tmpl_id)
        if not to_process:
            return self.env["product.template"]
        Product = self.env["product.template"].with_context(
            tracking_disable=True, mail_create_nolog=True
        )
        existing = {
            p.barcode: p
            for p in Product.search([("barcode", "in", to_process.mapped("cip13"))])
        }
        linked = Product.browse()
        vals_list, pending = [], self.browse()
        for pres in to_process:
            product = existing.get(pres.cip13)
            if product:
                product.pharma_presentation_id = pres
                pres.product_tmpl_id = product
                linked |= product
            else:
                vals_list.append(pres._prepare_product_vals())
                pending |= pres
        created = Product.create(vals_list)
        for pres, product in zip(pending, created, strict=True):
            pres.product_tmpl_id = product
        return linked | created

    def action_create_products(self):
        products = self._create_products()
        if not products:
            raise UserError(
                "Les présentations sélectionnées sont déjà référencées comme articles."
            )
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "pharma_fr_base.action_pharma_product_template"
        )
        action["domain"] = [("id", "in", products.ids)]
        return action

    def action_open_product(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "product.template",
            "res_id": self.product_tmpl_id.id,
            "view_mode": "form",
        }
