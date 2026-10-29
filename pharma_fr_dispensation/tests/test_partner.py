from odoo.exceptions import ValidationError
from odoo.tests import tagged

from ..models.res_partner import nir_is_valid
from .common import PharmaDispensationCase


@tagged("post_install", "-at_install", "pharma")
class TestPartner(PharmaDispensationCase):

    def test_nir(self):
        self.assertTrue(nir_is_valid("1 85 05 78 006 084 91"))
        self.assertTrue(nir_is_valid("2 90 02 2A 123 456 78"))
        self.assertFalse(nir_is_valid("1 85 05 78 006 084 92"))
        self.assertFalse(nir_is_valid("123"))
        with self.assertRaises(ValidationError):
            self.patient.pharma_nir = "1 85 05 78 006 084 00"

    def test_rpps(self):
        with self.assertRaises(ValidationError):
            self.doctor.pharma_rpps = "12345"

    def test_age(self):
        self.assertEqual(self.patient.pharma_age, 45)
        self.assertEqual(self.senior.pharma_age, 75)
