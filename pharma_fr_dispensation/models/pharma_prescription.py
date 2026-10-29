from dateutil.relativedelta import relativedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round

from .pharma_prescription_line import split_amounts

# Durée de validité d'une ordonnance pour une première délivrance.
PRESCRIPTION_VALIDITY_MONTHS = 3


class PharmaPrescription(models.Model):
    """Ordonnance dispensée : lignes délivrées, honoraires, répartition entre
    payeurs (AMO, AMC, patient), sortie de stock et facturation."""

    _name = "pharma.prescription"
    _description = "Ordonnance"
    _inherit = ["mail.thread"]
    _order = "dispensing_date desc, id desc"

    name = fields.Char("Référence", default="/", copy=False, readonly=True, index=True)
    state = fields.Selection(
        [("draft", "En cours"), ("done", "Délivrée"), ("cancel", "Annulée")],
        default="draft", required=True, tracking=True, index=True, copy=False,
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    warehouse_id = fields.Many2one(
        "stock.warehouse", string="Officine (entrepôt)", required=True,
        default=lambda self: self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        ),
    )
    patient_id = fields.Many2one(
        "res.partner", string="Patient", required=True, index=True, tracking=True,
        domain=[("pharma_partner_type", "=", "patient")],
    )
    prescriber_id = fields.Many2one(
        "res.partner", string="Prescripteur", index=True, tracking=True,
        domain=[("pharma_partner_type", "=", "prescriber")],
    )
    prescription_date = fields.Date(
        "Date de prescription", required=True, default=fields.Date.context_today,
    )
    dispensing_date = fields.Datetime(
        "Date de délivrance", required=True, default=fields.Datetime.now, index=True,
    )
    prescription_type = fields.Selection(
        [
            ("standard", "Ordonnance simple"),
            ("bizone", "Ordonnance bizone (ALD)"),
            ("secure", "Ordonnance sécurisée"),
        ],
        string="Type d'ordonnance", default="standard", required=True,
    )
    renewal_index = fields.Integer(
        "Renouvellement n°", default=0,
        help="0 pour la première délivrance, puis 1, 2... pour les renouvellements.",
    )
    line_ids = fields.One2many(
        "pharma.prescription.line", "prescription_id", string="Lignes", copy=True,
    )
    fee_ids = fields.One2many(
        "pharma.prescription.fee", "prescription_id", string="Honoraires d'ordonnance",
    )
    picking_id = fields.Many2one("stock.picking", string="Sortie de stock", copy=False)
    invoice_ids = fields.Many2many("account.move", string="Factures", copy=False)
    invoice_count = fields.Integer(compute="_compute_invoice_count")
    note = fields.Text("Notes")

    amount_total = fields.Monetary("Total TTC", compute="_compute_totals", store=True)
    amount_amo = fields.Monetary("Part AMO", compute="_compute_totals", store=True)
    amount_amc = fields.Monetary("Part AMC", compute="_compute_totals", store=True)
    amount_patient = fields.Monetary("Reste à charge", compute="_compute_totals", store=True)
    amount_fees = fields.Monetary("Honoraires TTC", compute="_compute_totals", store=True)
    amount_untaxed = fields.Monetary("Total HT", compute="_compute_totals", store=True)
    amount_cost = fields.Monetary("Coût d'achat", compute="_compute_totals", store=True)
    margin = fields.Monetary("Marge brute HT", compute="_compute_totals", store=True)
    substitutable_count = fields.Integer(
        "Lignes substituables", compute="_compute_totals", store=True,
        help="Lignes délivrées en générique ou dont le princeps a un groupe générique.",
    )
    generic_count = fields.Integer("Lignes en générique", compute="_compute_totals", store=True)

    # ------------------------------------------------------------------
    # Calculs
    # ------------------------------------------------------------------

    @api.depends(
        "line_ids.amount_total", "line_ids.amount_amo", "line_ids.amount_amc",
        "line_ids.amount_patient", "line_ids.amount_untaxed", "line_ids.amount_cost",
        "line_ids.box_fee", "line_ids.quantity", "line_ids.is_generic",
        "fee_ids.amount_total", "fee_ids.amount_amo", "fee_ids.amount_amc",
        "fee_ids.amount_patient",
    )
    def _compute_totals(self):
        for rx in self:
            lines, fees = rx.line_ids, rx.fee_ids
            rx.amount_total = sum(lines.mapped("amount_total")) + sum(fees.mapped("amount_total"))
            rx.amount_amo = sum(lines.mapped("amount_amo")) + sum(fees.mapped("amount_amo"))
            rx.amount_amc = sum(lines.mapped("amount_amc")) + sum(fees.mapped("amount_amc"))
            rx.amount_patient = (
                sum(lines.mapped("amount_patient")) + sum(fees.mapped("amount_patient"))
            )
            rx.amount_fees = (
                sum(line.box_fee * line.quantity for line in lines)
                + sum(fees.mapped("amount_total"))
            )
            fees_untaxed = sum(
                fee.amount_total / (1 + rx._pharma_fee_vat(fee.product_id) / 100) for fee in fees
            )
            rx.amount_untaxed = sum(lines.mapped("amount_untaxed")) + fees_untaxed
            rx.amount_cost = sum(lines.mapped("amount_cost"))
            rx.margin = rx.amount_untaxed - rx.amount_cost
            substitutable = lines.filtered(
                lambda line: line.product_id.pharma_generic_group_id
            )
            rx.substitutable_count = len(substitutable)
            rx.generic_count = len(substitutable.filtered("is_generic"))

    def _compute_invoice_count(self):
        for rx in self:
            rx.invoice_count = len(rx.invoice_ids)

    def _pharma_fee_vat(self, product):
        taxes = product.taxes_id.filtered(lambda t: t.company_id == self.company_id)
        return sum(taxes.mapped("amount"))

    def _pharma_is_exempt(self):
        self.ensure_one()
        patient = self.patient_id
        return patient.pharma_exemption == "c2s" or (
            patient.pharma_exemption == "ald" and any(self.line_ids.mapped("ald_related"))
        )

    def _pharma_applicable_fee_codes(self):
        """Honoraires d'ordonnance dus selon le contenu de l'ordonnance."""
        self.ensure_one()
        reimbursable = self.line_ids.filtered("reimbursement_rate")
        if not reimbursable:
            return []
        codes = ["prescription"]
        age = self.patient_id._pharma_age_at(fields.Date.to_date(self.dispensing_date))
        if self.patient_id.pharma_birthdate and (age < 3 or age >= 70):
            codes.append("age")
        if len(reimbursable.mapped("product_id")) >= 5:
            codes.append("complex")
        if any(reimbursable.mapped("product_id.pharma_is_narcotic")):
            codes.append("specific")
        return codes

    def _pharma_recompute_fees(self):
        """Recalcule les honoraires d'ordonnance des ordonnances en cours."""
        Rule = self.env["pharma.fee.rule"]
        for rx in self.filtered(lambda r: r.state == "draft"):
            on_date = fields.Date.to_date(rx.dispensing_date)
            patient = rx.patient_id
            exempt = rx._pharma_is_exempt()
            amc_coverage = patient.pharma_amc_coverage if patient.pharma_amc_id else "none"
            commands = [Command.clear()]
            for code in rx._pharma_applicable_fee_codes():
                rule = Rule._get_rule(code, on_date)
                if not rule:
                    continue
                # L'honoraire d'ordonnance complexe est exonéré du ticket modérateur.
                rate = 100.0 if (exempt or code == "complex") else rule.reimbursement_rate
                total, amo, amc, rest = split_amounts(
                    1, rule.amount, 0.0, rule.amount, rate, False, amc_coverage,
                    bool(patient.pharma_tiers_payant),
                )
                commands.append(Command.create({
                    "rule_id": rule.id,
                    "amount_total": total,
                    "reimbursement_rate": rate,
                    "amount_amo": amo,
                    "amount_amc": amc,
                    "amount_patient": rest,
                }))
            rx.with_context(pharma_skip_fees=True).fee_ids = commands

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("pharma.prescription") or "/"
        records = super().create(vals_list)
        records._pharma_recompute_fees()
        return records

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("pharma_skip_fees") and {
            "patient_id", "dispensing_date", "line_ids"
        } & set(vals):
            self._pharma_recompute_fees()
        return result

    # ------------------------------------------------------------------
    # Contrôles
    # ------------------------------------------------------------------

    def _pharma_check_before_dispensing(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError("Seule une ordonnance en cours peut être délivrée.")
        if not self.line_ids:
            raise UserError("L'ordonnance ne comporte aucune ligne.")
        drugs = self.line_ids.filtered(
            lambda line: line.product_id.pharma_category in ("drug_reimbursed", "drug_otc")
        )
        listed = drugs.filtered(
            lambda line: line.product_id.pharma_prescription_list not in (False, "none")
        )
        if (listed or drugs.filtered("reimbursement_rate")) and not self.prescriber_id:
            raise UserError("Le prescripteur est obligatoire pour cette ordonnance.")
        limit = fields.Date.to_date(self.dispensing_date) - relativedelta(
            months=PRESCRIPTION_VALIDITY_MONTHS
        )
        if listed and self.renewal_index == 0 and self.prescription_date < limit:
            raise UserError(
                "Ordonnance expirée : plus de 3 mois depuis la prescription "
                "pour une première délivrance."
            )
        narcotics = drugs.filtered(lambda line: line.product_id.pharma_is_narcotic)
        if narcotics and self.prescription_type != "secure":
            raise UserError(
                "Les stupéfiants et assimilés exigent une ordonnance sécurisée : "
                + ", ".join(narcotics.mapped("product_id.display_name"))
            )
        hospital = drugs.filtered(lambda line: line.product_id.pharma_specialite_id.hospital_reserved)
        if hospital:
            raise UserError(
                "Médicament réservé à l'usage hospitalier : "
                + ", ".join(hospital.mapped("product_id.display_name"))
            )
        patient = self.patient_id
        if sum(self.line_ids.mapped("amount_amo")) + sum(self.fee_ids.mapped("amount_amo")) and \
                not patient.pharma_amo_id:
            raise UserError(f"Caisse d'assurance maladie non renseignée pour {patient.name}.")

    # ------------------------------------------------------------------
    # Délivrance
    # ------------------------------------------------------------------

    def action_dispense(self):
        for rx in self:
            rx._pharma_recompute_fees()
            rx._pharma_check_before_dispensing()
            rx._pharma_create_picking()
            rx._pharma_create_invoices()
            rx.state = "done"
        return True

    def _pharma_create_picking(self):
        self.ensure_one()
        lines = self.line_ids.filtered(lambda line: line.product_id.is_storable)
        for line in self.line_ids:
            line.unit_cost = line.product_id.standard_price
        if not lines:
            return
        warehouse = self.warehouse_id
        customers = self.env.ref("stock.stock_location_customers")
        picking = self.env["stock.picking"].create({
            "picking_type_id": warehouse.out_type_id.id,
            "partner_id": self.patient_id.id,
            "location_id": warehouse.lot_stock_id.id,
            "location_dest_id": customers.id,
            "origin": self.name,
            "move_ids": [
                Command.create({
                    "product_id": line.product_id.id,
                    "product_uom_qty": line.quantity,
                    "location_id": warehouse.lot_stock_id.id,
                    "location_dest_id": customers.id,
                })
                for line in lines
            ],
        })
        picking.action_confirm()
        picking.action_assign()
        missing = [
            f"{move.product_id.display_name} ({move.quantity:g}/{move.product_uom_qty:g})"
            for move in picking.move_ids
            if float_compare(move.quantity, move.product_uom_qty,
                             precision_rounding=move.product_uom.rounding) < 0
        ]
        if missing:
            raise UserError("Stock insuffisant : " + ", ".join(missing))
        now = self.dispensing_date
        expired = picking.move_line_ids.filtered(
            lambda ml: ml.lot_id.expiration_date and ml.lot_id.expiration_date < now
        )
        if expired:
            raise UserError(
                "Lots périmés réservés : "
                + ", ".join(f"{ml.product_id.display_name} lot {ml.lot_id.name}" for ml in expired)
            )
        picking.move_ids.picked = True
        picking.with_context(skip_backorder=True, skip_sms=True).button_validate()
        if picking.state != "done":
            raise UserError("La sortie de stock n'a pas pu être validée.")
        for line in lines:
            move_lines = picking.move_line_ids.filtered(lambda ml, pl=line: ml.product_id == pl.product_id)
            line.lot_names = ", ".join(sorted(set(move_lines.lot_id.mapped("name")))) or False
        self.picking_id = picking

    def _pharma_invoice_price(self, product, amount_ttc, quantity):
        """Prix unitaire à facturer selon que la taxe de l'article est TTC ou HT."""
        taxes = product.taxes_id.filtered(lambda t: t.company_id == self.company_id)
        unit = amount_ttc / quantity
        if not taxes or all(taxes.mapped("price_include")):
            return unit
        return unit / (1 + sum(taxes.mapped("amount")) / 100)

    def _pharma_invoice_lines(self, payer):
        """Lignes de facture de la part ``payer`` ('amo', 'amc', 'patient')."""
        self.ensure_one()
        box_fee_product = self.env.ref("pharma_fr_dispensation.product_fee_box")
        field = f"amount_{payer}"
        vals = []
        for line in self.line_ids:
            share = line[field]
            if not share:
                continue
            gross = line.unit_price + line.box_fee
            fee_part = float_round(share * line.box_fee / gross, precision_digits=2) if gross else 0.0
            product_part = share - fee_part
            if product_part:
                vals.append(Command.create({
                    "product_id": line.product_id.id,
                    "quantity": line.quantity,
                    "price_unit": self._pharma_invoice_price(
                        line.product_id, product_part, line.quantity
                    ),
                }))
            if fee_part:
                vals.append(Command.create({
                    "product_id": box_fee_product.id,
                    "name": f"Honoraire à la boîte - {line.product_id.display_name}",
                    "quantity": line.quantity,
                    "price_unit": self._pharma_invoice_price(
                        box_fee_product, fee_part, line.quantity
                    ),
                }))
        for fee in self.fee_ids:
            share = fee[field]
            if share:
                vals.append(Command.create({
                    "product_id": fee.product_id.id,
                    "quantity": 1,
                    "price_unit": self._pharma_invoice_price(fee.product_id, share, 1),
                }))
        return vals

    def _pharma_create_invoices(self):
        self.ensure_one()
        payers = {
            "amo": self.patient_id.pharma_amo_id,
            "amc": self.patient_id.pharma_amc_id,
            "patient": self.patient_id,
        }
        self.env["product.template"].with_company(self.company_id)._pharma_ensure_fee_taxes()
        moves = self.env["account.move"]
        for payer, partner in payers.items():
            lines = self._pharma_invoice_lines(payer)
            if not lines:
                continue
            if not partner:
                raise UserError(f"Organisme payeur manquant pour la part {payer.upper()}.")
            moves |= self.env["account.move"].create({
                "move_type": "out_invoice",
                "company_id": self.company_id.id,
                "partner_id": partner.id,
                "invoice_date": fields.Date.to_date(self.dispensing_date),
                "invoice_origin": f"{self.name} - {self.patient_id.name}",
                "ref": f"{self.name} ({payer.upper()})",
                "invoice_line_ids": lines,
            })
        moves.action_post()
        self.invoice_ids = moves

    def action_cancel(self):
        if any(rx.state == "done" for rx in self):
            raise UserError(
                "Une ordonnance délivrée ne peut pas être annulée : émettez un avoir "
                "et un retour de stock."
            )
        self.state = "cancel"
        return True

    def action_draft(self):
        self.filtered(lambda rx: rx.state == "cancel").state = "draft"
        return True

    def action_view_invoices(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("account.action_move_out_invoice_type")
        action["domain"] = [("id", "in", self.invoice_ids.ids)]
        action["context"] = {"create": False}
        return action

    def action_view_picking(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "res_id": self.picking_id.id,
            "view_mode": "form",
        }
