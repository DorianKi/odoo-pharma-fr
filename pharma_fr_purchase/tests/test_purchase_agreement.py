from odoo.tests import tagged

from ..models.purchase_order_line import _cap_advantages
from .common import PharmaPurchaseCase


@tagged("post_install", "-at_install", "pharma")
class TestPurchaseAgreement(PharmaPurchaseCase):

    def test_cap_categories(self):
        self.assertEqual(self.princeps.pharma_discount_cap_category, "base")
        self.assertEqual(self.generic.pharma_discount_cap_category, "generic")
        self.assertEqual(self.otc.pharma_discount_cap_category, "none")
        self.assertEqual(self.para.pharma_discount_cap_category, "none")
        self.princeps.pharma_is_biosimilar = True
        self.assertEqual(self.princeps.pharma_discount_cap_category, "biosimilar")

    def test_cap_advantages_helper(self):
        self.assertEqual(_cap_advantages(50, 0, 40), (40, 0.0, True))
        discount, rebate, capped = _cap_advantages(30, 20, 40)
        self.assertTrue(capped)
        self.assertAlmostEqual((1 - (1 - discount / 100) * (1 - rebate / 100)) * 100, 40, places=2)
        self.assertEqual(_cap_advantages(10, 5, None), (10, 5, False))

    def test_discounts_on_order(self):
        order = self._order([(self.princeps, 10), (self.generic, 10), (self.otc, 10), (self.para, 6)])
        lines = {line.product_id.product_tmpl_id: line for line in order.order_line}
        self.assertEqual(order.pharma_order_type, "wholesaler")
        self.assertEqual(order.pharma_agreement_id, self.agreement)

        # Princeps : condition « tous produits » 5 % ramenée au plafond de 2,5 %
        princeps = lines[self.princeps]
        self.assertEqual(princeps.price_unit, 1.10)
        self.assertEqual(princeps.discount, 2.5)
        self.assertTrue(princeps.pharma_discount_capped)
        self.assertFalse(princeps.pharma_over_cap)

        # Générique : la condition laboratoire (45 %) l'emporte, plafonnée à 40 %
        generic = lines[self.generic]
        self.assertEqual(generic.pharma_agreement_line_id.laboratory_id, self.generix)
        self.assertEqual(generic.discount, 40.0)
        self.assertEqual(generic.pharma_deferred_rebate, 0.0)
        self.assertEqual(generic.pharma_cap_rate, 40.0)

        # Non remboursable : prix libre, pas de plafond
        self.assertEqual(lines[self.otc].discount, 5.0)
        self.assertFalse(lines[self.otc].pharma_has_cap)

        # Parapharmacie : condition article à partir de 6 unités
        self.assertEqual(lines[self.para].discount, 12.0)

    def test_min_qty(self):
        order = self._order([(self.para, 2)])
        self.assertEqual(order.order_line.discount, 5.0)
        order.order_line.product_qty = 6
        self.assertEqual(order.order_line.discount, 12.0)

    def test_deferred_rebate_capped(self):
        # Sans la condition laboratoire, le segment générique s'applique : 35 % + 10 %
        self.agreement.line_ids.filtered("laboratory_id").unlink()
        line = self._order([(self.generic, 10)]).order_line
        self.assertEqual(line.discount, 35.0)
        self.assertTrue(line.pharma_discount_capped)
        self.assertAlmostEqual(line.pharma_total_advantage, 40.0, places=2)
        self.assertAlmostEqual(line.pharma_net_price_unit, 0.90 * 0.60, places=4)
        self.assertGreater(line.order_id.pharma_deferred_rebate_amount, 0)

    def test_dated_cap(self):
        self.env["pharma.discount.cap"].create({
            "name": "Génériques (nouveau plafond)", "cap_category": "generic",
            "rate": 30.0, "date_from": "2026-09-01",
        })
        before = self._order([(self.generic, 10)], date="2026-08-15 10:00:00").order_line
        after = self._order([(self.generic, 10)], date="2026-10-15 10:00:00").order_line
        self.assertEqual(before.discount, 40.0)
        self.assertEqual(after.discount, 30.0)

    def test_manual_discount_over_cap(self):
        order = self._order([(self.generic, 10)])
        order.order_line.discount = 50.0
        self.assertTrue(order.order_line.pharma_over_cap)
        self.assertTrue(order.pharma_has_over_cap)
        order.action_pharma_apply_agreement()
        self.assertEqual(order.order_line.discount, 40.0)
        self.assertFalse(order.pharma_has_over_cap)

    def test_franco(self):
        order = self._order([(self.otc, 10)])  # 10 × 2,50 × 0,95 = 23,75 HT
        self.assertTrue(order.pharma_below_franco)
        self.assertAlmostEqual(order.pharma_franco_missing, 150 - order.amount_untaxed)
        order.order_line.product_qty = 100
        self.assertFalse(order.pharma_below_franco)

    def test_direct_order_without_agreement(self):
        order = self._order([(self.generic, 10)], partner=self.generix)
        self.assertEqual(order.pharma_order_type, "direct")
        self.assertFalse(order.pharma_agreement_id)
        self.assertFalse(order.order_line.pharma_agreement_line_id)

    def test_expired_agreement_ignored(self):
        self.agreement.date_end = "2026-06-30"
        order = self._order([(self.otc, 10)])
        self.assertFalse(order.pharma_agreement_id)
        self.assertEqual(order.order_line.discount, 0.0)
