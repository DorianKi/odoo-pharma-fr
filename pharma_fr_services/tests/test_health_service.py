from odoo.addons.pharma_fr_dispensation.tests.common import PharmaDispensationCase
from odoo.tests import tagged


@tagged("post_install", "-at_install", "pharma")
class TestHealthService(PharmaDispensationCase):

    def test_trod_split_and_invoices(self):
        trod = self.env.ref("pharma_fr_services.type_trod_angine")
        service = self.env["pharma.health.service"].create({
            "type_id": trod.id, "patient_id": self.patient.id,
        })
        self.assertEqual(service.amount_total, 10.0)
        self.assertEqual((service.amount_amo, service.amount_amc, service.amount_patient),
                         (7.0, 3.0, 0.0))
        service.action_done()
        self.assertEqual(service.state, "done")
        self.assertEqual(set(service.invoice_ids.partner_id.ids), {self.cpam.id, self.mutuelle.id})
        self.assertAlmostEqual(sum(service.invoice_ids.mapped("amount_total")), 10.0)
        self.assertFalse(service.invoice_ids.invoice_line_ids.tax_ids)

    def test_vaccination_fully_covered(self):
        flu = self.env.ref("pharma_fr_services.type_flu_vaccination")
        service = self.env["pharma.health.service"].create({
            "type_id": flu.id, "patient_id": self.senior.id,
        })
        self.assertEqual(service.amount_amo, 7.5)
        self.assertEqual(service.amount_patient, 0.0)
