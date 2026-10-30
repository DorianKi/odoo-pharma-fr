from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models


class PharmaCashForecast(models.Model):
    """Trésorerie prévisionnelle au jour le jour.

    Encaissements attendus : factures clients ouvertes, à la date prévue d'après le
    délai de paiement de chaque payeur (AMO, mutuelles, patients). Décaissements :
    factures fournisseurs ouvertes à leur échéance. Les montants en retard sont
    reportés sur le premier jour de la prévision.
    """

    _name = "pharma.cash.forecast"
    _description = "Trésorerie prévisionnelle"
    _order = "date"

    date = fields.Date("Date", required=True, index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    inflow_amo = fields.Monetary("Encaissements AMO")
    inflow_amc = fields.Monetary("Encaissements mutuelles")
    inflow_other = fields.Monetary("Autres encaissements")
    outflow_suppliers = fields.Monetary("Règlements fournisseurs")
    net = fields.Monetary("Flux net")
    balance = fields.Monetary("Trésorerie prévue")
    overdue_in = fields.Monetary("Dont créances en retard")
    overdue_out = fields.Monetary("Dont dettes échues")

    @api.model
    def _cash_balance(self, company, on_date):
        lines = self.env["account.move.line"].search([
            ("company_id", "=", company.id), ("parent_state", "=", "posted"),
            ("account_id.account_type", "=", "asset_cash"), ("date", "<=", on_date),
        ])
        return sum(lines.mapped("balance"))

    @api.model
    def _compute_forecast(self, horizon=60, on_date=None, company=None):
        company = company or self.env.company
        start = on_date or fields.Date.context_today(self)
        self.search([("company_id", "=", company.id)]).unlink()
        flows = defaultdict(lambda: defaultdict(float))
        Move = self.env["account.move"]
        receivables = Move.search([
            ("company_id", "=", company.id), ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"), ("amount_residual", ">", 0),
        ])
        for inv in receivables:
            partner = inv.partner_id.commercial_partner_id
            expected = (inv.invoice_date or start) + timedelta(days=partner._pharma_expected_delay())
            day = max(expected, start)
            key = {"amo": "inflow_amo", "amc": "inflow_amc"}.get(partner.pharma_insurer_type,
                                                                 "inflow_other")
            flows[day][key] += inv.amount_residual
            if expected < start:
                flows[day]["overdue_in"] += inv.amount_residual
        payables = Move.search([
            ("company_id", "=", company.id), ("move_type", "=", "in_invoice"),
            ("state", "=", "posted"), ("amount_residual", ">", 0),
        ])
        for bill in payables:
            due = bill.invoice_date_due or bill.invoice_date or start
            day = max(due, start)
            flows[day]["outflow_suppliers"] += bill.amount_residual
            if due < start:
                flows[day]["overdue_out"] += bill.amount_residual
        balance = self._cash_balance(company, start - timedelta(days=1))
        vals_list = []
        for offset in range(horizon + 1):
            day = start + timedelta(days=offset)
            f = flows.get(day, {})
            net = (f.get("inflow_amo", 0) + f.get("inflow_amc", 0) + f.get("inflow_other", 0)
                   - f.get("outflow_suppliers", 0))
            balance += net
            vals_list.append({
                "date": day, "company_id": company.id,
                "inflow_amo": f.get("inflow_amo", 0), "inflow_amc": f.get("inflow_amc", 0),
                "inflow_other": f.get("inflow_other", 0),
                "outflow_suppliers": f.get("outflow_suppliers", 0),
                "net": net, "balance": balance,
                "overdue_in": f.get("overdue_in", 0), "overdue_out": f.get("overdue_out", 0),
            })
        return self.create(vals_list)

    @api.model
    def action_refresh(self):
        self._compute_forecast()
        return self.env["ir.actions.act_window"]._for_xml_id(
            "pharma_fr_analytics.action_pharma_cash_forecast"
        )
