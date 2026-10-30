from datetime import timedelta

from odoo import Command, fields
from odoo.addons.pharma_fr_regulatory.tests.common import PharmaRegulatoryCase
from odoo.tests import tagged


@tagged("post_install", "-at_install", "pharma")
class TestReports(PharmaRegulatoryCase):

    def test_cash_forecast(self):
        rx = self._prescription(lines=[(self.princeps, 2)])
        rx.action_dispense()  # factures AMO et AMC (facturation à l'acte)
        bill = self.env["account.move"].create({
            "move_type": "in_invoice", "partner_id": self.supplier.id,
            "invoice_date": fields.Date.today(),
            "invoice_date_due": fields.Date.today() + timedelta(days=10),
            "invoice_line_ids": [Command.create({"product_id": self.princeps.id, "quantity": 10,
                                                 "price_unit": 1.0, "tax_ids": [Command.clear()]})],
        })
        bill.action_post()
        self.cpam.pharma_payment_delay_days = 4
        forecast = self.env["pharma.cash.forecast"]._compute_forecast(horizon=30)
        today = fields.Date.today()
        by_date = {f.date: f for f in forecast}
        self.assertEqual(len(forecast), 31)
        self.assertAlmostEqual(by_date[today + timedelta(days=4)].inflow_amo, 2.83 + 0.43, places=2)
        self.assertAlmostEqual(by_date[today + timedelta(days=20)].inflow_amc, 1.53 + 0.18, places=2)
        self.assertAlmostEqual(by_date[today + timedelta(days=10)].outflow_suppliers, 10.0)
        self.assertAlmostEqual(forecast[-1].balance - forecast[0].balance + forecast[0].net,
                               sum(forecast.mapped("net")), places=2)

    def test_inventory_gap(self):
        quant = self.env["stock.quant"].search([
            ("product_id", "=", self.princeps.id), ("lot_id.name", "=", "LOT-A"),
            ("location_id", "=", self.warehouse.lot_stock_id.id),
        ])
        quant.with_context(inventory_mode=True).inventory_quantity = 47
        quant.action_apply_inventory()
        gap = self.env["pharma.inventory.gap"].search([("product_id", "=", self.princeps.id)])
        self.assertEqual((gap.theoretical_qty, gap.counted_qty, gap.gap_qty), (50, 47, -3))
        self.assertAlmostEqual(gap.gap_value, -3 * 0.80)

    def test_analysis_views(self):
        self.generic.standard_price = 0.50
        rx = self._prescription(lines=[(self.generic, 2, {"prescribed_product_id": self.princeps.id}),
                                       (self.princeps, 1, {"non_substitutable": True})])
        rx.action_dispense()
        self.env["pharma.stock.snapshot"]._take_snapshot(company=self.env.company)
        self.env.flush_all()
        loyalty = self.env["pharma.patient.loyalty"].search([("patient_id", "=", self.patient.id)])
        self.assertEqual(loyalty.status, "new")
        self.assertEqual(loyalty.visit_count, 1)
        perf = self.env["pharma.product.performance"].search([("product_id", "=", self.generic.id)])
        self.assertEqual(perf.quantity, 2)
        self.assertIn(perf.abc_class, ("A", "B", "C"))
        self.assertGreater(perf.avg_stock_value, 0)
        generic = self.env["pharma.prescriber.generic.report"].search(
            [("prescriber_id", "=", self.doctor.id)])
        self.assertEqual((generic.substitutable_lines, generic.generic_lines,
                          generic.non_substitutable_lines), (2, 1, 1))
        self.assertAlmostEqual(generic.generic_rate, 50.0)
        seller = self.env["pharma.seller.report"].search([("seller_id", "=", self.env.user.id)])
        self.assertEqual(seller.visits, 1)
        self.assertAlmostEqual(seller.revenue, rx.amount_total)
