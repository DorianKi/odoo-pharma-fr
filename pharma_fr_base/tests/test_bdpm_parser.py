from datetime import date

from odoo.tests import BaseCase, tagged

from ..lib import bdpm


@tagged("post_install", "-at_install", "pharma")
class TestBdpmParser(BaseCase):

    def test_file_key(self):
        self.assertEqual(bdpm.file_key("CIS_bdpm.txt"), "cis")
        self.assertEqual(bdpm.file_key("export/CIS_CIP_bdpm.txt"), "cis_cip")
        self.assertEqual(bdpm.file_key("CIS_CIP_Dispo_Spec.txt"), "dispo")
        self.assertIsNone(bdpm.file_key("autre.txt"))

    def test_prices_and_dates(self):
        self.assertEqual(bdpm.parse_price("2,18"), 2.18)
        self.assertEqual(bdpm.parse_price("1 234,56"), 1234.56)
        self.assertEqual(bdpm.parse_price("1,234,56"), 1234.56)
        self.assertIsNone(bdpm.parse_price(""))
        self.assertEqual(bdpm.parse_date("16/03/2011"), date(2011, 3, 16))
        self.assertIsNone(bdpm.parse_date("31/02/2011"))

    def test_rates(self):
        self.assertEqual(bdpm.parse_rates("65%;100 %"), ["65", "100"])
        self.assertEqual(bdpm.parse_rates(""), [])

    def test_mixed_encoding(self):
        content = "60000001\tPARACÉTAMOL\n".encode("cp1252") + "60000002\tIBUPROFÈNE\n".encode()
        rows = list(bdpm.iter_rows(content))
        self.assertEqual(rows[0][1], "PARACÉTAMOL")
        self.assertEqual(rows[1][1], "IBUPROFÈNE")

    def test_classify_conditions(self):
        c = bdpm.classify_conditions
        self.assertEqual(c(["liste I"])["prescription_list"], "list_1")
        self.assertEqual(c(["Liste II"])["prescription_list"], "list_2")
        narcotic = c(["stupéfiant", "prescription limitée à 28 jours"])
        self.assertEqual(narcotic["prescription_list"], "narcotic")
        self.assertTrue(narcotic["narcotic_rules"])
        assimilated = c(["liste I", "règles de prescription des stupéfiants"])
        self.assertEqual(assimilated["prescription_list"], "list_1")
        self.assertTrue(assimilated["narcotic_rules"])
        self.assertTrue(c(["réservé à l'usage HOSPITALIER"])["hospital_reserved"])
        self.assertEqual(c([])["prescription_list"], "none")

    def test_presentations_11_columns(self):
        line = "60000001\t3000001\tboîte de 8\tPrésentation active\t" \
               "Déclaration de commercialisation\t12/05/2001\t3400930000011\toui\t65%\t2,18\t\n"
        pres = bdpm.parse_presentations(line.encode())["3400930000011"]
        self.assertEqual(pres["price_ttc"], 2.18)
        self.assertEqual(pres["dispensing_fee"], 0.0)
        self.assertEqual(pres["reimbursement_rate"], "65")

    def test_availability_keeps_latest(self):
        content = (
            "60000004\t\t2\tTension\t01/08/2026\t01/08/2026\t\t\n"
            "60000004\t\t1\tRupture\t05/10/2026\t20/10/2026\t\t\n"
        ).encode()
        self.assertEqual(bdpm.parse_availability(content)["60000004"]["availability_status"], "shortage")
