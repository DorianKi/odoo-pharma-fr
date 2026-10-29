from odoo import api, fields, models


class PharmaGenericGroup(models.Model):
    _name = "pharma.generic.group"
    _description = "Groupe générique"
    _order = "name"

    code = fields.Char("Identifiant BDPM", required=True, index=True)
    name = fields.Char("Libellé", required=True)
    specialite_ids = fields.One2many(
        "pharma.specialite", "generic_group_id", string="Spécialités"
    )
    princeps_id = fields.Many2one(
        "pharma.specialite", compute="_compute_princeps", string="Princeps", store=True
    )
    specialite_count = fields.Integer(compute="_compute_princeps", store=True)
    generic_count = fields.Integer(
        compute="_compute_princeps", string="Nb génériques", store=True
    )

    _code_uniq = models.Constraint(
        "unique (code)", "Ce groupe générique existe déjà."
    )

    @api.depends("specialite_ids.generic_type")
    def _compute_princeps(self):
        for group in self:
            princeps = group.specialite_ids.filtered(
                lambda s: s.generic_type == "princeps"
            )
            group.princeps_id = princeps[:1]
            group.specialite_count = len(group.specialite_ids)
            group.generic_count = len(group.specialite_ids - princeps)
