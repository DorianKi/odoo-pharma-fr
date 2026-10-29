from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import PharmaRegulatoryCase


@tagged("post_install", "-at_install", "pharma")
class TestExpiryAndReturns(PharmaRegulatoryCase):

    def _qty(self, product):
        return product.with_context(warehouse_id=self.warehouse.id).qty_available

    def test_expiry_scrap(self):
        expired = self._add_stock(
            self.princeps, "LOT-PERIME", 7, fields.Datetime.now() - timedelta(days=10)
        )
        wizard = self.env["pharma.expiry.scrap.wizard"].create({})
        self.assertIn(expired, wizard.quant_ids.lot_id)
        self.assertFalse(wizard.quant_ids.filtered(lambda q: q.lot_id.name == "LOT-A"))
        before = self._qty(self.princeps)
        wizard.action_scrap()
        self.assertEqual(self._qty(self.princeps), before - 7)
        scrap = self.env["stock.scrap"].search([("lot_id", "=", expired.id)])
        self.assertEqual(scrap.state, "done")
        self.assertIn("Périmé", scrap.scrap_reason_tag_ids.mapped("name"))
        self.assertIn("Lots détruits : 1", wizard.result)

    def test_expiry_scrap_nothing(self):
        wizard = self.env["pharma.expiry.scrap.wizard"].create({})
        wizard.quant_ids = False
        with self.assertRaises(UserError):
            wizard.action_scrap()

    def test_return_restock(self):
        rx = self._prescription(lines=[(self.princeps, 2)])
        rx.action_dispense()
        self.assertEqual(self._qty(self.princeps), 98)
        wizard = self.env["pharma.prescription.return.wizard"].create({
            "prescription_id": rx.id, "reason": "Erreur au comptoir", "restock": True,
        })
        wizard.action_confirm()
        self.assertEqual(rx.state, "returned")
        self.assertEqual(self._qty(self.princeps), 100)
        self.assertEqual(rx.return_picking_id.state, "done")
        self.assertEqual(rx.return_picking_id.move_line_ids.lot_id.name, "LOT-A")
        self.assertFalse(rx.return_scrap_ids)
        self.assertEqual(len(rx.refund_ids), len(rx.invoice_ids))
        self.assertTrue(all(m.state == "posted" and m.move_type == "out_refund" for m in rx.refund_ids))
        self.assertAlmostEqual(
            sum(rx.refund_ids.mapped("amount_total")), sum(rx.invoice_ids.mapped("amount_total"))
        )

    def test_return_destroy(self):
        rx = self._prescription(lines=[(self.princeps, 2)])
        rx.action_dispense()
        rx._pharma_return("Produit rapporté par le patient")
        self.assertEqual(self._qty(self.princeps), 98)
        self.assertEqual(rx.return_scrap_ids.mapped("state"), ["done"])
        self.assertIn("Retour patient", rx.return_scrap_ids.scrap_reason_tag_ids.mapped("name"))

    def test_return_requires_dispensed(self):
        rx = self._prescription(lines=[(self.princeps, 1)])
        with self.assertRaises(UserError):
            rx._pharma_return("test")
