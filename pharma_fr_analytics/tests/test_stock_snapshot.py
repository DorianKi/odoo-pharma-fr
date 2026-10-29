from datetime import timedelta

from odoo import fields
from odoo.addons.pharma_fr_regulatory.tests.common import PharmaRegulatoryCase
from odoo.tests import tagged


@tagged("post_install", "-at_install", "pharma")
class TestStockSnapshot(PharmaRegulatoryCase):

    def _snap(self, product):
        return self.env["pharma.stock.snapshot"].search(
            [("product_id", "=", product.id), ("date", "=", fields.Date.today())]
        )

    def test_snapshot(self):
        self._add_stock(self.princeps, "LOT-COURT", 5, fields.Datetime.now() + timedelta(days=30))
        rx = self._prescription(lines=[(self.princeps, 3)])
        rx.action_dispense()
        Snapshot = self.env["pharma.stock.snapshot"]
        Snapshot._take_snapshot(company=self.env.company)
        snap = self._snap(self.princeps)
        self.assertEqual(snap.quantity, 102)  # 100 + 5 - 3
        self.assertEqual(snap.sales_30d, 3)
        self.assertAlmostEqual(snap.daily_demand, 0.1)
        self.assertAlmostEqual(snap.coverage_days, 1020, places=0)
        self.assertEqual(snap.qty_expiring_90d, 2)  # FEFO : les 3 boîtes sortent du lot court
        self.assertAlmostEqual(snap.value, 102 * 0.80)
        self.assertEqual(snap.pharma_category, "drug_reimbursed")
        self.assertFalse(snap.is_dormant)
        # Sans vente : couverture « infinie » ; pas encore dormant (stock récent)
        generic = self._snap(self.generic)
        self.assertEqual(generic.coverage_days, 999)
        self.assertFalse(generic.is_dormant)
        # Stock présent depuis plus de 60 jours sans vente : dormant
        self._receive(self.generic, 5, "LOT-ANCIEN")
        moves = self.env["stock.move"].search([("product_id", "=", self.generic.id)])
        moves.write({"date": fields.Datetime.now() - timedelta(days=90)})
        Snapshot._take_snapshot(company=self.env.company)
        self.assertTrue(self._snap(self.generic).is_dormant)
        # Relancer le même jour remplace la photo
        Snapshot._take_snapshot(company=self.env.company)
        self.assertEqual(len(self._snap(self.princeps)), 1)
