from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import PharmaRegulatoryCase


@tagged("post_install", "-at_install", "pharma")
class TestRegisters(PharmaRegulatoryCase):

    def _register(self, product):
        return self.env["pharma.narcotic.register"].search(
            [("product_id", "=", product.id)], order="number"
        )

    def test_narcotic_register_lifecycle(self):
        receipt = self._receive(self.morphine, 10, "MORPH-01")
        entries = self._register(self.morphine)
        self.assertEqual(len(entries), 1)
        self.assertEqual((entries.kind, entries.quantity_in, entries.balance), ("receipt", 10, 10))
        self.assertEqual(entries.partner_id, self.supplier)
        self.assertEqual(entries.lot_names, "MORPH-01")
        self.assertEqual(entries.reference, receipt.name)

        rx = self._prescription(prescription_type="secure", lines=[(self.morphine, 2)])
        rx.action_dispense()
        out = self._register(self.morphine)[-1]
        self.assertEqual((out.kind, out.quantity_out, out.balance), ("dispensing", 2, 8))
        self.assertEqual(out.number, 2)
        self.assertEqual(out.partner_id, self.patient)
        self.assertEqual(out.prescriber_id, self.doctor)
        self.assertEqual(out.prescription_id, rx)

        # Retour patient avec destruction : entrée puis sortie au registre
        rx._pharma_return("Erreur de dosage")
        back, destroyed = self._register(self.morphine)[-2:]
        self.assertEqual((back.kind, back.quantity_in, back.balance), ("patient_return", 2, 10))
        self.assertEqual((destroyed.kind, destroyed.quantity_out, destroyed.balance),
                         ("destruction", 2, 8))

        with self.assertRaises(UserError):
            out.write({"quantity_out": 1})
        with self.assertRaises(UserError):
            out.unlink()

    def test_non_narcotic_not_registered(self):
        rx = self._prescription(lines=[(self.amox, 1)])
        rx.action_dispense()
        self.assertFalse(self._register(self.amox))

    def test_ordonnancier(self):
        self.patient.write({"street": "12 rue de Rivoli", "zip": "75004", "city": "Paris"})
        rx = self._prescription(lines=[(self.amox, 1), (self.princeps, 2)])
        rx.action_dispense()
        entry = rx.ordonnancier_ids
        self.assertEqual(len(entry), 1)  # seule l'amoxicilline (liste I) est inscrite
        self.assertEqual(entry.prescription_list, "list_1")
        self.assertEqual(entry.patient_name, "Jeanne Dupont")
        self.assertEqual(entry.patient_address, "12 rue de Rivoli, 75004, Paris")
        self.assertEqual(entry.prescriber_rpps, "10001234567")
        self.assertEqual(entry.lot_names, "LOT-A")
        rx2 = self._prescription(lines=[(self.amox, 1)])
        rx2.action_dispense()
        self.assertGreater(rx2.ordonnancier_ids.number, entry.number)
        with self.assertRaises(UserError):
            entry.write({"patient_name": "X"})

    def test_reports_render(self):
        self._receive(self.morphine, 5, "MORPH-02")
        rx = self._prescription(prescription_type="secure", lines=[(self.morphine, 1)])
        rx.action_dispense()
        Report = self.env["ir.actions.report"]
        html, _ = Report._render_qweb_html(
            "pharma_fr_regulatory.action_report_narcotic_register",
            self._register(self.morphine).ids,
        )
        self.assertIn("Registre des stupéfiants", html.decode())
        self.assertIn("MORPH-02", html.decode())
        html, _ = Report._render_qweb_html(
            "pharma_fr_regulatory.action_report_ordonnancier", rx.ordonnancier_ids.ids,
        )
        self.assertIn("Jeanne Dupont", html.decode())
