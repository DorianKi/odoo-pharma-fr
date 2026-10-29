from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from .common import PharmaPurchaseCase


@tagged("post_install", "-at_install", "pharma")
class TestReplenishment(PharmaPurchaseCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.stock = cls.warehouse.lot_stock_id
        cls.customers = cls.env.ref("stock.stock_location_customers")
        cls.cream = cls.para.product_variant_id
        cls.env["stock.quant"]._update_available_quantity(cls.cream, cls.stock, 500)

    def _sell(self, product, qty, days_ago):
        move = self.env["stock.move"].create({
            "product_id": product.id,
            "product_uom_qty": qty,
            "location_id": self.stock.id,
            "location_dest_id": self.customers.id,
        })
        move._action_confirm()
        move._action_assign()
        move.quantity = qty
        move.picked = True
        move._action_done()
        move.date = fields.Datetime.now() - timedelta(days=days_ago)
        return move

    def _run(self, **values):
        wizard = self.env["pharma.replenishment.wizard"].create(dict({
            "warehouse_id": self.warehouse.id,
            "product_tmpl_ids": [(6, 0, (self.para | self.otc).ids)],
            "history_days": 30,
            "coverage_days": 7,
            "safety_days": 2,
        }, **values))
        wizard.action_compute()
        return wizard

    def _orderpoint(self, product):
        return self.env["stock.warehouse.orderpoint"].search([
            ("product_id", "=", product.id), ("location_id", "=", self.stock.id),
        ])

    def test_thresholds(self):
        Wizard = self.env["pharma.replenishment.wizard"]
        self.assertEqual(Wizard._compute_thresholds(2.0, 1, 2, 7), (6, 20))
        self.assertEqual(Wizard._compute_thresholds(0.1, 1, 2, 7), (1, 2))
        self.assertEqual(Wizard._compute_thresholds(0, 1, 2, 7), (0, 0))

    def test_orderpoints_from_sales(self):
        # 60 unités vendues en 30 jours = 2 / jour ; délai fournisseur 1 j
        self._sell(self.cream, 40, days_ago=10)
        self._sell(self.cream, 20, days_ago=3)
        self._sell(self.cream, 100, days_ago=60)  # hors période
        wizard = self._run()
        orderpoint = self._orderpoint(self.cream)
        self.assertEqual(orderpoint.product_min_qty, 6)
        self.assertEqual(orderpoint.product_max_qty, 20)
        self.assertEqual(orderpoint.trigger, "auto")
        self.assertEqual(orderpoint.route_id, self.env.ref("purchase_stock.route_warehouse0_buy"))
        self.assertIn("Règles créées : 1", wizard.result)
        self.assertIn("sans vente sur 30 jours : 1", wizard.result)  # le médicament OTC

        # Deuxième passage : mise à jour, pas de doublon
        self._sell(self.cream, 30, days_ago=1)
        self._run()
        orderpoint = self._orderpoint(self.cream)
        self.assertEqual(len(orderpoint), 1)
        self.assertEqual(orderpoint.product_min_qty, 9)  # 3 / jour × 3 j

    def test_dormant_reset(self):
        self.env["stock.warehouse.orderpoint"].create({
            "product_id": self.otc.product_variant_id.id,
            "warehouse_id": self.warehouse.id,
            "location_id": self.stock.id,
            "product_min_qty": 5,
            "product_max_qty": 10,
        })
        self._run(deactivate_dormant=True)
        orderpoint = self._orderpoint(self.otc.product_variant_id)
        self.assertEqual((orderpoint.product_min_qty, orderpoint.product_max_qty), (0, 0))
