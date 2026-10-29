from datetime import timedelta

from odoo import Command, fields
from odoo.addons.pharma_fr_dispensation.tests.common import PharmaDispensationCase


class PharmaRegulatoryCase(PharmaDispensationCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.supplier = cls.env["res.partner"].create({
            "name": "Répartiteur Démo", "is_company": True, "pharma_partner_type": "wholesaler",
        })

    def _receive(self, product, qty, lot_name, days_to_expiry=365):
        stock = self.warehouse.lot_stock_id
        supplier_location = self.env.ref("stock.stock_location_suppliers")
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse.in_type_id.id,
            "partner_id": self.supplier.id,
            "location_id": supplier_location.id,
            "location_dest_id": stock.id,
            "move_ids": [Command.create({
                "product_id": product.id,
                "product_uom_qty": qty,
                "location_id": supplier_location.id,
                "location_dest_id": stock.id,
            })],
        })
        picking.action_confirm()
        picking.move_ids.move_line_ids = [Command.clear(), Command.create({
            "product_id": product.id,
            "lot_name": lot_name,
            "quantity": qty,
            "location_id": supplier_location.id,
            "location_dest_id": stock.id,
            "expiration_date": fields.Datetime.now() + timedelta(days=days_to_expiry),
        })]
        picking.move_ids.picked = True
        picking.with_context(skip_expired=True).button_validate()
        self.assertEqual(picking.state, "done")
        return picking
