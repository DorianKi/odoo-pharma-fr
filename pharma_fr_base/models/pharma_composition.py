from odoo import fields, models


class PharmaComposition(models.Model):
    _name = "pharma.composition"
    _description = "Composition d'une spécialité"
    _order = "specialite_id, link_number, nature, id"

    specialite_id = fields.Many2one(
        "pharma.specialite", required=True, ondelete="cascade", index=True
    )
    element = fields.Char("Élément pharmaceutique")
    substance_code = fields.Char("Code substance", index=True)
    substance_name = fields.Char("Substance", required=True)
    dosage = fields.Char("Dosage")
    dosage_reference = fields.Char("Référence du dosage")
    nature = fields.Selection(
        [
            ("SA", "Substance active"),
            ("FT", "Fraction thérapeutique"),
            ("ST", "Fraction thérapeutique (ST)"),
        ],
        default="SA",
        required=True,
    )
    link_number = fields.Integer("N° de liaison SA/FT")
