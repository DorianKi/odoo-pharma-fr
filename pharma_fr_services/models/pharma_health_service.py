from odoo import Command, api, fields, models
from odoo.addons.pharma_fr_dispensation.models.pharma_prescription_line import split_amounts
from odoo.exceptions import UserError

CATEGORY_SELECTION = [
    ("vaccination", "Vaccination"),
    ("test", "Test rapide (TROD)"),
    ("interview", "Entretien / bilan"),
]


class PharmaHealthServiceType(models.Model):
    _name = "pharma.health.service.type"
    _description = "Type de mission de santé"
    _order = "category, name"

    name = fields.Char("Mission", required=True)
    code = fields.Char("Code acte", required=True)
    category = fields.Selection(CATEGORY_SELECTION, required=True)
    amount = fields.Float("Honoraire TTC", required=True, digits="Product Price")
    amo_rate = fields.Float("Prise en charge AMO (%)", required=True, default=70.0)
    duration_minutes = fields.Integer("Durée moyenne (min)", default=15,
                                      help="Sert à estimer la rentabilité horaire des missions.")
    product_id = fields.Many2one("product.product", "Article de facturation", required=True,
                                 domain=[("type", "=", "service")])
    active = fields.Boolean(default=True)


class PharmaHealthService(models.Model):
    """Mission de santé réalisée à l'officine (acte facturé à l'assurance maladie)."""

    _name = "pharma.health.service"
    _description = "Mission de santé"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char("Référence", default="/", readonly=True, copy=False)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date = fields.Datetime("Date", required=True, default=fields.Datetime.now, index=True)
    type_id = fields.Many2one("pharma.health.service.type", "Mission", required=True, index=True)
    category = fields.Selection(related="type_id.category", store=True)
    patient_id = fields.Many2one("res.partner", "Patient", required=True, index=True,
                                 domain=[("pharma_partner_type", "=", "patient")])
    pharmacist_id = fields.Many2one("res.users", "Réalisé par", default=lambda self: self.env.user,
                                    index=True)
    duration_minutes = fields.Integer("Durée (min)", compute="_compute_from_type", store=True,
                                      readonly=False)
    amount_total = fields.Monetary("Honoraire TTC", compute="_compute_from_type", store=True,
                                   readonly=False)
    amount_amo = fields.Monetary("Part AMO", compute="_compute_split", store=True)
    amount_amc = fields.Monetary("Part AMC", compute="_compute_split", store=True)
    amount_patient = fields.Monetary("Part patient", compute="_compute_split", store=True)
    state = fields.Selection([("draft", "Planifiée"), ("done", "Réalisée"), ("cancel", "Annulée")],
                             default="draft", required=True, tracking=True, index=True)
    invoice_ids = fields.Many2many("account.move", string="Factures", copy=False)
    note = fields.Text("Observations")

    @api.depends("type_id")
    def _compute_from_type(self):
        for service in self:
            service.amount_total = service.type_id.amount
            service.duration_minutes = service.type_id.duration_minutes

    @api.depends("amount_total", "type_id.amo_rate", "patient_id.pharma_exemption",
                 "patient_id.pharma_amc_id", "patient_id.pharma_amc_coverage")
    def _compute_split(self):
        for service in self:
            patient = service.patient_id
            exempt = patient.pharma_exemption in ("c2s", "ald")
            coverage = patient.pharma_amc_coverage if patient.pharma_amc_id else "none"
            _total, amo, amc, rest = split_amounts(
                1, service.amount_total, 0.0, service.amount_total, service.type_id.amo_rate,
                exempt, coverage, True,
            )
            service.amount_amo, service.amount_amc, service.amount_patient = amo, amc, rest

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("pharma.health.service") or "/"
        return super().create(vals_list)

    def action_done(self):
        for service in self.filtered(lambda s: s.state == "draft"):
            patient = service.patient_id
            payers = [("amo", patient.pharma_amo_id), ("amc", patient.pharma_amc_id),
                      ("patient", patient)]
            vals_list = []
            for payer, partner in payers:
                amount = service[f"amount_{payer}"]
                if not amount:
                    continue
                if not partner:
                    raise UserError(f"Organisme payeur manquant pour {patient.name}.")
                vals_list.append({
                    "move_type": "out_invoice",
                    "company_id": service.company_id.id,
                    "partner_id": partner.id,
                    "invoice_date": fields.Date.to_date(service.date),
                    "ref": f"{service.name} ({payer.upper()})",
                    "invoice_origin": service.name,
                    "invoice_line_ids": [Command.create({
                        "product_id": service.type_id.product_id.id,
                        "name": f"{service.type_id.name} - {patient.name}",
                        "quantity": 1,
                        "price_unit": amount,
                        "tax_ids": [Command.clear()],
                    })],
                })
            moves = self.env["account.move"].create(vals_list)
            moves.action_post()
            service.write({"state": "done", "invoice_ids": [Command.set(moves.ids)]})
        return True

    def action_cancel(self):
        if any(s.state == "done" for s in self):
            raise UserError("Une mission réalisée et facturée ne peut pas être annulée.")
        self.state = "cancel"
        return True
