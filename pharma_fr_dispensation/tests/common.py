import os
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

BDPM_DATA = os.path.join(
    os.path.dirname(__file__), "..", "..", "pharma_fr_base", "tests", "data"
)


class PharmaDispensationCase(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("fr")
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref("pharma_fr_base.group_pharma_manager")
        cls.env["product.template"].search([("pharma_presentation_id", "!=", False)]).write(
            {"pharma_presentation_id": False, "barcode": False, "active": False}
        )
        cls.env["pharma.specialite"].search([]).unlink()
        cls.env["pharma.bdpm.importer"].import_directory(BDPM_DATA, create_products="marketed")
        cls.env["product.template"]._pharma_ensure_fee_taxes()

        Product = cls.env["product.product"]
        cls.princeps = Product.search([("barcode", "=", "3400930000011")])   # 1,16 € + 1,02, 65 %
        cls.generic = Product.search([("barcode", "=", "3400930000028")])    # 0,99 € + 1,02, 65 %
        cls.amox = Product.search([("barcode", "=", "3400930000035")])       # liste I, 3,52 €
        cls.morphine = Product.search([("barcode", "=", "3400930000059")])   # stupéfiant
        cls.zolpidem = Product.search([("barcode", "=", "3400930000066")])   # 15 %, assimilé
        cls.otc = Product.search([("barcode", "=", "3400930000042")])        # non remboursable
        cls.otc.lst_price = 3.90
        cls.princeps.standard_price = 0.80

        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.warehouse.lot_stock_id.removal_strategy_id = cls.env.ref("product_expiry.removal_fefo")
        cls.stock = cls.warehouse.lot_stock_id
        future = fields.Datetime.now() + timedelta(days=365)
        for product in (cls.princeps, cls.generic, cls.amox, cls.zolpidem, cls.otc):
            cls._add_stock(product, "LOT-B", 50, future + timedelta(days=200))
            cls._add_stock(product, "LOT-A", 50, future)

        Partner = cls.env["res.partner"]
        cls.cpam = Partner.create({
            "name": "CPAM du Rhône", "is_company": True,
            "pharma_partner_type": "insurer", "pharma_insurer_type": "amo",
            "pharma_insurer_code": "01691",
        })
        cls.mutuelle = Partner.create({
            "name": "Mutuelle Démo", "is_company": True,
            "pharma_partner_type": "insurer", "pharma_insurer_type": "amc",
        })
        cls.doctor = Partner.create({
            "name": "Dr Martin", "pharma_partner_type": "prescriber",
            "pharma_rpps": "10001234567", "pharma_specialty": "Médecine générale",
        })
        cls.patient = Partner.create({
            "name": "Jeanne Dupont", "pharma_partner_type": "patient",
            "pharma_birthdate": date.today() - relativedelta(years=45),
            "pharma_nir": "2 81 05 69 123 456 90",
            "pharma_amo_id": cls.cpam.id, "pharma_amc_id": cls.mutuelle.id,
            "pharma_amc_coverage": "tm",
        })
        cls.senior = Partner.create({
            "name": "Paul Bernard", "pharma_partner_type": "patient",
            "pharma_birthdate": date.today() - relativedelta(years=75),
            "pharma_amo_id": cls.cpam.id,
        })

    @classmethod
    def _add_stock(cls, product, lot_name, qty, expiration):
        lot = cls.env["stock.lot"].create({
            "name": lot_name, "product_id": product.id, "expiration_date": expiration,
        })
        cls.env["stock.quant"]._update_available_quantity(product, cls.stock, qty, lot_id=lot)
        return lot

    def _prescription(self, patient=None, lines=(), **values):
        return self.env["pharma.prescription"].create(dict({
            "patient_id": (patient or self.patient).id,
            "prescriber_id": self.doctor.id,
            "line_ids": [
                Command.create(dict({"product_id": product.id, "quantity": qty}, **extra))
                for product, qty, extra in (
                    (item[0], item[1], item[2] if len(item) > 2 else {}) for item in lines
                )
            ],
        }, **values))
