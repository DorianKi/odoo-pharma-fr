from odoo import Command, fields, models
from odoo.exceptions import UserError


class PharmaPrescription(models.Model):
    _inherit = "pharma.prescription"

    state = fields.Selection(
        selection_add=[("returned", "Retournée")],
        ondelete={"returned": "set default"},
    )
    ordonnancier_ids = fields.One2many(
        "pharma.ordonnancier", "prescription_id", string="Inscriptions à l'ordonnancier"
    )
    return_picking_id = fields.Many2one("stock.picking", "Retour en stock", copy=False)
    return_scrap_ids = fields.Many2many("stock.scrap", string="Destructions", copy=False)
    refund_ids = fields.Many2many(
        "account.move", "pharma_prescription_refund_rel", string="Avoirs", copy=False
    )
    return_reason = fields.Char("Motif du retour", copy=False)

    def action_dispense(self):
        result = super().action_dispense()
        for prescription in self:
            self.env["pharma.ordonnancier"]._record_prescription(prescription)
        return result

    # ------------------------------------------------------------------
    # Retours patient
    # ------------------------------------------------------------------

    def _pharma_return(self, reason, restock=False):
        """Annule une délivrance : avoirs pour chaque payeur, retour des lots en
        stock puis, sauf remise en stock autorisée, destruction.

        Un médicament rapporté par un patient ne peut pas être redélivré : la
        remise en stock n'est admise que si le produit n'a pas quitté l'officine
        (erreur de saisie au comptoir, par exemple).
        """
        self.ensure_one()
        if self.state != "done":
            raise UserError("Seule une ordonnance délivrée peut faire l'objet d'un retour.")
        if self.picking_id:
            self._pharma_create_return_picking()
            if not restock:
                self._pharma_destroy_returned()
        if self.invoice_ids:
            refunds = self.invoice_ids._reverse_moves(
                default_values_list=[
                    {"ref": f"Retour {self.name} : {reason}", "invoice_date": fields.Date.today()}
                    for _invoice in self.invoice_ids
                ],
            )
            refunds.action_post()
            self.refund_ids = refunds
        self.write({"state": "returned", "return_reason": reason})
        self.message_post(body=f"Retour patient : {reason}"
                          + (" (remise en stock)" if restock else " (destruction)"))

    def _pharma_create_return_picking(self):
        """Retour de la totalité de la délivrance, lots compris (assistant standard
        de retour d'Odoo), rattaché à l'ordonnance par sa référence."""
        wizard = self.env["stock.return.picking"].create({"picking_id": self.picking_id.id})
        action = wizard.action_create_returns_all()
        ret = self.env["stock.picking"].browse(action["res_id"])
        ret.origin = self.name
        stock = self.warehouse_id.lot_stock_id
        if ret.location_dest_id != stock:
            ret.location_dest_id = stock
            ret.move_ids.location_dest_id = stock
        for move in ret.move_ids:
            returned = move.origin_returned_move_id
            if move.move_line_ids.lot_id != returned.move_line_ids.lot_id:
                move.move_line_ids = [Command.clear()] + [
                    Command.create({
                        "product_id": line.product_id.id,
                        "lot_id": line.lot_id.id,
                        "quantity": line.quantity,
                        "location_id": move.location_id.id,
                        "location_dest_id": stock.id,
                    })
                    for line in returned.move_line_ids
                ]
        ret.move_ids.picked = True
        ret.with_context(skip_backorder=True, skip_sms=True, skip_expired=True).button_validate()
        if ret.state != "done":
            raise UserError("Le retour en stock n'a pas pu être validé.")
        self.return_picking_id = ret

    def _pharma_destroy_returned(self):
        tag = self.env.ref("pharma_fr_regulatory.scrap_reason_patient_return")
        scraps = self.env["stock.scrap"]
        for line in self.return_picking_id.move_line_ids:
            scraps |= self.env["stock.scrap"].create({
                "product_id": line.product_id.id,
                "lot_id": line.lot_id.id,
                "scrap_qty": line.quantity,
                "location_id": line.location_dest_id.id,
                "company_id": self.company_id.id,
                "origin": self.name,
                "scrap_reason_tag_ids": [Command.set(tag.ids)],
            })
        scraps.do_scrap()
        self.return_scrap_ids = scraps

    def action_open_return_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Retour patient",
            "res_model": "pharma.prescription.return.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_prescription_id": self.id},
        }
