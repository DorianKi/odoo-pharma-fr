import os

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from ..lib import bdpm

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


@tagged("post_install", "-at_install", "pharma")
class TestBdpmImport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.importer = cls.env["pharma.bdpm.importer"]
        cls.files = cls.importer.read_directory(DATA_DIR)

    def _import(self, **kwargs):
        return self.importer.import_files(self.files, **kwargs)

    def test_full_import(self):
        stats = self._import()
        self.assertEqual(stats["specialites_created"], 7)
        self.assertEqual(stats["presentations_created"], 7)
        self.assertEqual(stats["generic_groups_created"], 2)
        Spec = self.env["pharma.specialite"]

        princeps = Spec.search([("cis_code", "=", "60000001")])
        self.assertEqual(princeps.generic_type, "princeps")
        self.assertEqual(princeps.laboratory_id.name, "LABORATOIRES DEMOPHARM")
        self.assertEqual(princeps.laboratory_id.pharma_partner_type, "laboratory")
        self.assertEqual(princeps.active_substances, "PARACÉTAMOL")
        self.assertTrue(princeps.is_marketed)
        self.assertEqual(princeps.generic_group_id.princeps_id, princeps)
        self.assertEqual(princeps.generic_group_id.generic_count, 1)

        amox = Spec.search([("cis_code", "=", "60000003")])
        self.assertEqual(amox.prescription_list, "list_1")
        self.assertEqual(amox.availability_status, "tension")
        self.assertTrue(amox.is_mitm)
        self.assertEqual(amox.atc_code, "J01CA04")
        self.assertEqual(len(amox.composition_ids), 2)
        self.assertEqual(amox.active_substances, "AMOXICILLINE TRIHYDRATÉE")

        self.assertEqual(Spec.search([("cis_code", "=", "60000004")]).availability_status, "shortage")
        morphine = Spec.search([("cis_code", "=", "60000005")])
        self.assertEqual(morphine.prescription_list, "narcotic")
        self.assertTrue(morphine.reinforced_monitoring)
        zolpidem = Spec.search([("cis_code", "=", "60000006")])
        self.assertEqual(zolpidem.prescription_list, "list_1")
        self.assertTrue(zolpidem.narcotic_rules)
        old = Spec.search([("cis_code", "=", "60000007")])
        self.assertFalse(old.is_marketed)
        self.assertTrue(old.hospital_reserved)

        pres = self.env["pharma.presentation"].search([("cip13", "=", "3400930000059")])
        self.assertEqual(pres.price_ttc, 1234.56)
        self.assertEqual(pres.dispensing_fee, 1.02)
        self.assertEqual(pres.reimbursement_rate, "65")
        self.assertTrue(pres.is_marketed)
        # Fichier encodé en Windows-1252 : les accents doivent être corrects
        self.assertIn("Présentation", pres.admin_status)

    def test_reimport_is_idempotent(self):
        self._import()
        stats = self._import()
        self.assertEqual(stats["specialites_created"], 0)
        self.assertEqual(stats["specialites_updated"], 0)
        self.assertEqual(stats["presentations_created"], 0)
        self.assertEqual(stats["presentations_updated"], 0)

    def test_update_detects_changes(self):
        self._import()
        files = dict(self.files)
        files["cis_cip"] = files["cis_cip"].replace(b"\t1,16\t", b"\t1,20\t")
        stats = self.importer.import_files({"cis_cip": files["cis_cip"]})
        self.assertEqual(stats["presentations_updated"], 1)
        pres = self.env["pharma.presentation"].search([("cip13", "=", "3400930000011")])
        self.assertEqual(pres.price_ttc, 1.20)

    def test_create_products_reimbursed(self):
        stats = self._import(create_products="marketed_reimbursed")
        # 7 présentations : 1 non commercialisée, 1 non remboursable
        self.assertEqual(stats["products_created"], 5)
        product = self.env["product.template"].search([("barcode", "=", "3400930000011")])
        self.assertEqual(product.pharma_category, "drug_reimbursed")
        self.assertEqual(product.pharma_price_regime, "regulated")
        self.assertEqual(product.pharma_vat_rate, "2.1")
        self.assertEqual(product.tracking, "lot")
        self.assertTrue(product.is_storable)
        self.assertTrue(product.use_expiration_date)
        self.assertEqual(product.pharma_generic_type, "princeps")
        self.assertEqual(product.pharma_laboratory_id.name, "LABORATOIRES DEMOPHARM")
        self.assertEqual(product.pharma_public_price, 1.16)
        sale_tax = product.taxes_id[:1]
        if sale_tax:  # plan comptable installé
            self.assertEqual(sale_tax.amount, 2.1)
            expected = 1.16 if sale_tax.price_include else round(1.16 / 1.021, 4)
            self.assertAlmostEqual(product.list_price, expected, places=2)
        morphine = self.env["product.template"].search([("barcode", "=", "3400930000059")])
        self.assertTrue(morphine.pharma_is_narcotic)

    def test_create_products_all_marketed_and_limit(self):
        self._import()
        products = self.importer._create_products("marketed", limit=2)
        self.assertEqual(len(products), 2)
        products |= self.importer._create_products("marketed")
        self.assertEqual(len(products), 6)
        otc = products.filtered(lambda p: p.barcode == "3400930000042")
        self.assertEqual(otc.pharma_category, "drug_otc")
        self.assertEqual(otc.pharma_vat_rate, "10")
        self.assertEqual(otc.pharma_price_regime, "free")
        # Une seconde passe ne crée pas de doublon
        self.assertFalse(self.importer._create_products("marketed"))

    def test_link_existing_product_by_barcode(self):
        self._import()
        existing = self.env["product.template"].create({
            "name": "Article saisi à la main", "barcode": "3400930000011",
        })
        pres = self.env["pharma.presentation"].search([("cip13", "=", "3400930000011")])
        pres.action_create_products()
        self.assertEqual(pres.product_tmpl_id, existing)
        self.assertEqual(existing.pharma_presentation_id, pres)

    def test_parapharmacy_product(self):
        product = self.env["product.template"].create({
            "name": "Crème hydratante", "pharma_category": "parapharmacy",
        })
        self.assertEqual(product.pharma_vat_rate, "20")
        self.assertEqual(product.pharma_price_regime, "free")

    def test_import_requires_manager(self):
        user = new_test_user(self.env, "prep", groups="pharma_fr_base.group_pharma_user")
        with self.assertRaises(UserError):
            self.importer.with_user(user).import_files(self.files)

    def test_import_without_specialites_fails(self):
        with self.assertRaises(UserError):
            self.importer.import_files({"cis_cip": self.files["cis_cip"]})

    def test_wizard_zip(self):
        import base64
        import io
        import zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name in os.listdir(DATA_DIR):
                with open(os.path.join(DATA_DIR, name), "rb") as fh:
                    archive.writestr(f"bdpm/{name}", fh.read())
        wizard = self.env["pharma.bdpm.import.wizard"].create({
            "zip_file": base64.b64encode(buffer.getvalue()),
            "create_products": "marketed",
        })
        wizard.action_import()
        self.assertEqual(wizard.state, "done")
        self.assertIn("Articles officine créés ou reliés : 6", wizard.result)
        self.assertEqual(set(bdpm.FILE_KEYS.values()), set(self.files))
