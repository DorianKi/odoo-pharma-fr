from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from ..models.pharma_prescription_line import split_amounts, unit_count
from .common import PharmaDispensationCase


@tagged("post_install", "-at_install", "pharma")
class TestDispensation(PharmaDispensationCase):

    def test_helpers(self):
        self.assertEqual(split_amounts(2, 2.18, 1.02, 2.18, 65, False, "tm", True),
                         (6.4, 4.16, 2.24, 0.0))
        self.assertEqual(split_amounts(1, 2.0, 1.0, 2.0, 65, True, "none", True),
                         (3.0, 3.0, 0.0, 0.0))
        self.assertEqual(split_amounts(1, 2.0, 1.0, 2.0, 65, False, "tm", False),
                         (3.0, 0.0, 0.0, 3.0))
        self.assertEqual(split_amounts(1, 1.72, 1.02, 1.72, 15, False, "tm_except_15", True),
                         (2.74, 0.41, 0.0, 2.33))
        self.assertEqual(unit_count("plaquette(s) PVC de 30 gélule(s)"), 30)

    def test_amounts_and_fees(self):
        rx = self._prescription(lines=[(self.princeps, 2)])
        line = rx.line_ids
        self.assertEqual(line.reimbursement_rate, 65)
        self.assertEqual((line.unit_price, line.box_fee), (1.16, 1.02))
        self.assertEqual(line.amount_total, 4.36)
        self.assertEqual(line.amount_amo, 2.83)
        self.assertEqual(line.amount_amc, 1.53)
        self.assertEqual(line.amount_patient, 0.0)
        self.assertEqual(rx.fee_ids.mapped("code"), ["prescription"])
        fee = rx.fee_ids
        self.assertEqual((fee.amount_total, fee.amount_amo, fee.amount_amc), (0.61, 0.43, 0.18))
        self.assertAlmostEqual(rx.amount_total, 4.97)
        self.assertAlmostEqual(rx.amount_fees, 2.65)
        self.assertAlmostEqual(rx.amount_patient, 0.0)

    def test_dispense_stock_and_invoices(self):
        rx = self._prescription(lines=[(self.princeps, 2)])
        rx.action_dispense()
        self.assertEqual(rx.state, "done")
        self.assertEqual(rx.picking_id.state, "done")
        # FEFO : le lot qui périme le premier sort en premier
        self.assertEqual(rx.line_ids.lot_names, "LOT-A")
        self.assertEqual(self.princeps.with_context(warehouse_id=self.warehouse.id).qty_available, 98)
        self.assertEqual(rx.line_ids.unit_cost, 0.80)
        self.assertAlmostEqual(rx.line_ids.margin, round(4.36 / 1.021, 2) - 1.60, places=2)
        invoices = rx.invoice_ids
        self.assertEqual(len(invoices), 2)  # AMO + AMC, rien à la charge du patient
        self.assertTrue(all(move.state == "posted" for move in invoices))
        amo = invoices.filtered(lambda m: m.partner_id == self.cpam)
        amc = invoices.filtered(lambda m: m.partner_id == self.mutuelle)
        self.assertAlmostEqual(amo.amount_total, 2.83 + 0.43, places=2)
        self.assertAlmostEqual(amc.amount_total, 1.53 + 0.18, places=2)
        self.assertAlmostEqual(sum(invoices.mapped("amount_total")), rx.amount_total, places=2)
        self.assertTrue(all(invoices.invoice_line_ids.tax_ids.mapped(lambda t: t.amount == 2.1)))

    def test_senior_complex_specific_fees(self):
        rx = self._prescription(
            patient=self.senior, prescription_type="secure",
            lines=[(self.princeps, 1), (self.generic, 1), (self.amox, 1),
                   (self.morphine, 1), (self.zolpidem, 1)],
        )
        self.assertEqual(set(rx.fee_ids.mapped("code")),
                         {"prescription", "age", "complex", "specific"})
        complex_fee = rx.fee_ids.filtered(lambda f: f.code == "complex")
        self.assertEqual(complex_fee.reimbursement_rate, 100)
        # Sans complémentaire : le patient règle le ticket modérateur
        age_fee = rx.fee_ids.filtered(lambda f: f.code == "age")
        self.assertEqual(age_fee.amount_amc, 0.0)
        self.assertAlmostEqual(age_fee.amount_patient, 1.68 - age_fee.amount_amo, places=2)
        # Retirer une ligne fait disparaître l'honoraire d'ordonnance complexe
        rx.line_ids[-1].unlink()
        self.assertNotIn("complex", rx.fee_ids.mapped("code"))

    def test_substitution_refused(self):
        rx = self._prescription(lines=[(self.princeps, 1, {"substitution_refused": True})])
        line = rx.line_ids
        self.assertEqual(line.base_unit, 0.99)  # générique le plus cher, même conditionnement
        self.assertFalse(line.tiers_payant)
        self.assertEqual(line.amount_patient, line.amount_total)
        line.non_substitutable = True  # mention « non substituable » du prescripteur
        self.assertEqual(line.base_unit, 1.16)
        self.assertTrue(line.tiers_payant)

    def test_substitution_tracking(self):
        rx = self._prescription(lines=[(self.generic, 1, {"prescribed_product_id": self.princeps.id})])
        self.assertTrue(rx.line_ids.is_substitution)
        self.assertEqual((rx.substitutable_count, rx.generic_count), (1, 1))

    def test_exemptions(self):
        self.patient.pharma_exemption = "c2s"
        rx = self._prescription(lines=[(self.princeps, 1)])
        self.assertEqual(rx.line_ids.amount_amo, rx.line_ids.amount_total)
        self.assertEqual(rx.fee_ids.reimbursement_rate, 100)
        self.patient.pharma_exemption = "ald"
        rx = self._prescription(prescription_type="bizone", lines=[
            (self.princeps, 1, {"ald_related": True}), (self.amox, 1),
        ])
        ald_line, other = rx.line_ids
        self.assertEqual(ald_line.amount_amo, ald_line.amount_total)
        self.assertEqual(other.amount_amo, round(other.amount_total * 0.65, 2))

    def test_listed_otc_requires_prescriber(self):
        # Ibuprofène 400 mg : non remboursable mais inscrit sur la liste II
        rx = self._prescription(lines=[(self.otc, 1)], prescriber_id=False)
        self.assertEqual(rx.line_ids.vat_rate, 10.0)
        with self.assertRaisesRegex(UserError, "prescripteur"):
            rx.action_dispense()

    def test_parapharmacy_sale(self):
        cream = self.env["product.product"].create({
            "name": "Crème hydratante", "pharma_category": "parapharmacy",
            "is_storable": True, "list_price": 12.0,
        })
        self.env["stock.quant"]._update_available_quantity(cream, self.stock, 5)
        rx = self._prescription(lines=[(cream, 2)], prescriber_id=False)
        line = rx.line_ids
        self.assertFalse(rx.fee_ids)
        self.assertEqual(line.vat_rate, 20.0)
        self.assertEqual(line.amount_patient, line.amount_total)
        self.assertAlmostEqual(line.amount_untaxed * 1.2, line.amount_total, places=1)
        rx.action_dispense()
        self.assertEqual(rx.invoice_ids.partner_id, self.patient)
        self.assertAlmostEqual(rx.invoice_ids.amount_total, line.amount_total, places=2)

    def test_regulatory_checks(self):
        rx = self._prescription(lines=[(self.morphine, 1)])
        with self.assertRaisesRegex(UserError, "sécurisée"):
            rx.action_dispense()
        old = self._prescription(
            lines=[(self.amox, 1)],
            prescription_date=date.today() - relativedelta(months=4),
        )
        with self.assertRaisesRegex(UserError, "expirée"):
            old.action_dispense()
        no_doctor = self._prescription(lines=[(self.amox, 1)], prescriber_id=False)
        with self.assertRaisesRegex(UserError, "prescripteur"):
            no_doctor.action_dispense()

    def test_insufficient_stock(self):
        rx = self._prescription(lines=[(self.amox, 500)])
        with self.assertRaisesRegex(UserError, "Stock insuffisant"):
            rx.action_dispense()
        self.assertEqual(rx.state, "draft")
        self.assertFalse(rx.picking_id)

    def test_expired_lot_blocked(self):
        product = self.zolpidem
        self.env["stock.quant"].search([("product_id", "=", product.id)]).sudo().unlink()
        self._add_stock(product, "LOT-PERIME", 10, fields.Datetime.now() - relativedelta(days=5))
        rx = self._prescription(prescription_type="secure", lines=[(product, 1)])
        with self.assertRaises(UserError):
            rx.action_dispense()

    def test_cancel(self):
        rx = self._prescription(lines=[(self.princeps, 1)])
        rx.action_cancel()
        self.assertEqual(rx.state, "cancel")
        rx.action_draft()
        rx.action_dispense()
        with self.assertRaises(UserError):
            rx.action_cancel()

    def test_missing_item(self):
        item = self.env["pharma.missing.item"].create({
            "product_id": self.amox.id, "quantity": 2, "unit_price": 3.52,
            "reason": "national_shortage", "patient_id": self.patient.id,
        })
        self.assertAlmostEqual(item.amount_lost, 7.04)

    def test_daily_invoicing(self):
        counter = self.env["res.partner"].create({"name": "Encaissements comptoir"})
        self.env.company.write({
            "pharma_invoicing_mode": "daily", "pharma_counter_partner_id": counter.id,
        })
        rx1 = self._prescription(lines=[(self.princeps, 2)])
        rx2 = self._prescription(patient=self.senior, lines=[(self.amox, 1)])
        (rx1 | rx2).action_dispense()
        self.assertFalse(rx1.invoice_ids)
        moves = self.env["pharma.prescription"]._pharma_invoice_pending()
        # Un bordereau AMO commun, la mutuelle de la patiente, les encaissements comptoir
        self.assertEqual(set(moves.partner_id.ids), {self.cpam.id, self.mutuelle.id, counter.id})
        amo = moves.filtered(lambda m: m.partner_id == self.cpam)
        self.assertAlmostEqual(amo.amount_total, rx1.amount_amo + rx2.amount_amo, places=2)
        self.assertIn(amo, rx1.invoice_ids)
        self.assertIn(amo, rx2.invoice_ids)
        self.assertTrue(rx1.pharma_invoiced and rx2.pharma_invoiced)
        self.assertAlmostEqual(sum(moves.mapped("amount_total")), rx1.amount_total + rx2.amount_total,
                               places=2)
        self.assertFalse(self.env["pharma.prescription"]._pharma_invoice_pending())
        refunds = rx2._pharma_create_refunds("test")
        self.assertAlmostEqual(sum(refunds.mapped("amount_total")), rx2.amount_total, places=2)
        self.assertEqual(set(refunds.mapped("move_type")), {"out_refund"})
