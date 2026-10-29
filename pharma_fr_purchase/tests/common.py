import os

from odoo import Command
from odoo.tests import TransactionCase

BDPM_DATA = os.path.join(
    os.path.dirname(__file__), "..", "..", "pharma_fr_base", "tests", "data"
)


class PharmaPurchaseCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        importer = cls.env["pharma.bdpm.importer"]
        cls.env["product.template"].search([("pharma_presentation_id", "!=", False)]).write(
            {"pharma_presentation_id": False, "barcode": False, "active": False}
        )
        cls.env["pharma.specialite"].search([]).unlink()
        importer.import_directory(BDPM_DATA, create_products="marketed")
        Product = cls.env["product.template"]
        cls.princeps = Product.search([("barcode", "=", "3400930000011")])
        cls.generic = Product.search([("barcode", "=", "3400930000028")])
        cls.otc = Product.search([("barcode", "=", "3400930000042")])
        cls.para = Product.create({
            "name": "Crème hydratante 50 ml",
            "pharma_category": "parapharmacy",
            "is_storable": True,
            "barcode": "3700000000017",
        })
        cls.wholesaler = cls.env["res.partner"].create({
            "name": "Répartiteur Démo",
            "is_company": True,
            "pharma_partner_type": "wholesaler",
            "pharma_franco_amount": 150.0,
            "pharma_is_main_wholesaler": True,
        })
        cls.generix = cls.generic.pharma_laboratory_id
        prices = {cls.princeps: 1.10, cls.generic: 0.90, cls.otc: 2.50, cls.para: 4.00}
        cls.env["product.supplierinfo"].create([
            {"partner_id": cls.wholesaler.id, "product_tmpl_id": tmpl.id, "price": price, "delay": 1}
            for tmpl, price in prices.items()
        ])
        cls.agreement = cls.env["pharma.purchase.agreement"].create({
            "name": "Accord 2026",
            "partner_id": cls.wholesaler.id,
            "date_start": "2026-01-01",
            "line_ids": [
                Command.create({"scope": "all", "discount": 5.0}),
                Command.create({"scope": "generic", "discount": 35.0, "deferred_rebate": 10.0}),
                Command.create({"scope": "generic", "laboratory_id": cls.generix.id,
                                "discount": 45.0}),
                Command.create({"product_tmpl_id": cls.para.id, "discount": 12.0,
                                "min_qty": 6}),
            ],
        })

    def _order(self, lines, partner=None, date="2026-10-15 10:00:00"):
        return self.env["purchase.order"].create({
            "partner_id": (partner or self.wholesaler).id,
            "date_order": date,
            "order_line": [
                Command.create({"product_id": tmpl.product_variant_id.id, "product_qty": qty})
                for tmpl, qty in lines
            ],
        })
