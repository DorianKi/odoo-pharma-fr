from odoo import api, fields, models
from odoo.exceptions import UserError

MOVE_KIND_SELECTION = [
    ("receipt", "Entrée (fournisseur)"),
    ("patient_return", "Retour patient"),
    ("dispensing", "Sortie (délivrance)"),
    ("supplier_return", "Retour fournisseur"),
    ("destruction", "Destruction"),
    ("adjustment", "Régularisation d'inventaire"),
]


class PharmaNarcoticRegister(models.Model):
    """Registre des stupéfiants (art. R. 5132-36 du code de la santé publique).

    Chaque entrée et sortie de stupéfiant y est inscrite automatiquement à la
    validation du mouvement de stock, avec le solde par produit. Les lignes ne
    peuvent être ni modifiées ni supprimées : une erreur se corrige par une
    régularisation.
    """

    _name = "pharma.narcotic.register"
    _description = "Registre des stupéfiants"
    _order = "date desc, id desc"
    _rec_name = "number"

    number = fields.Integer("N° d'ordre", readonly=True, index=True)
    company_id = fields.Many2one("res.company", required=True, readonly=True, index=True)
    date = fields.Datetime("Date", required=True, readonly=True, index=True)
    product_id = fields.Many2one("product.product", "Stupéfiant", required=True, readonly=True,
                                 index=True)
    kind = fields.Selection(MOVE_KIND_SELECTION, string="Nature", required=True, readonly=True)
    quantity_in = fields.Float("Entrée", digits="Product Unit", readonly=True)
    quantity_out = fields.Float("Sortie", digits="Product Unit", readonly=True)
    balance = fields.Float("Stock après opération", digits="Product Unit", readonly=True)
    lot_names = fields.Char("Lots", readonly=True)
    partner_id = fields.Many2one("res.partner", "Fournisseur / patient", readonly=True)
    prescriber_id = fields.Many2one("res.partner", "Prescripteur", readonly=True)
    prescription_id = fields.Many2one("pharma.prescription", "Ordonnance", readonly=True)
    move_id = fields.Many2one("stock.move", "Mouvement de stock", readonly=True, index=True)
    reference = fields.Char("Pièce", readonly=True)
    user_id = fields.Many2one("res.users", "Opérateur", readonly=True)

    @api.model
    def _kind_from_move(self, move):
        """Nature de l'opération d'après les emplacements du mouvement."""
        src, dest = move.location_id.usage, move.location_dest_id.usage
        if src != "internal" and dest == "internal":
            if src == "customer":
                return "patient_return", 1
            if src == "supplier":
                return "receipt", 1
            return "adjustment", 1
        if src == "internal" and dest != "internal":
            if move.scrap_id:
                return "destruction", -1
            if dest == "customer":
                return "dispensing", -1
            if dest == "supplier":
                return "supplier_return", -1
            return "adjustment", -1
        return None, 0

    @api.model
    def _register_moves(self, moves):
        """Inscrit les mouvements terminés portant sur des stupéfiants."""
        Prescription = self.env["pharma.prescription"]
        for move in moves.sorted(lambda m: (m.date, m.id)):
            product = move.product_id
            if product.pharma_prescription_list != "narcotic" or move.state != "done":
                continue
            kind, sign = self._kind_from_move(move)
            if not kind:
                continue
            company = move.company_id
            last = self.search(
                [("company_id", "=", company.id), ("product_id", "=", product.id)],
                order="number desc", limit=1,
            )
            qty = move.product_qty
            # Les sorties et retours d'ordonnance portent la référence de l'ordonnance.
            prescription = Prescription.browse()
            if move.picking_id.origin:
                prescription = Prescription.search(
                    [("name", "=", move.picking_id.origin), ("company_id", "=", company.id)],
                    limit=1,
                )
            self.sudo().create({
                "number": (last.number or 0) + 1,
                "company_id": company.id,
                "date": move.date,
                "product_id": product.id,
                "kind": kind,
                "quantity_in": qty if sign > 0 else 0.0,
                "quantity_out": qty if sign < 0 else 0.0,
                "balance": (last.balance or 0.0) + sign * qty,
                "lot_names": ", ".join(sorted(set(move.move_line_ids.lot_id.mapped("name")))),
                "partner_id": (prescription.patient_id or move.picking_id.partner_id).id or False,
                "prescriber_id": prescription.prescriber_id.id if prescription else False,
                "prescription_id": prescription.id if prescription else False,
                "move_id": move.id,
                "reference": move.reference or move.picking_id.name or move.scrap_id.name,
                "user_id": self.env.uid,
            })

    def write(self, vals):
        raise UserError("Le registre des stupéfiants ne peut pas être modifié.")

    def unlink(self):
        raise UserError("Le registre des stupéfiants ne peut pas être supprimé.")
