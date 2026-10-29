from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    pharma_partner_type = fields.Selection(
        selection=[
            ("laboratory", "Laboratoire"),
            ("wholesaler", "Grossiste-répartiteur"),
        ],
        string="Rôle officine",
        index=True,
        help="Rôle du partenaire dans la chaîne du médicament. "
             "Les laboratoires sont créés automatiquement à l'import BDPM "
             "(titulaires d'AMM).",
    )
    pharma_specialite_ids = fields.One2many(
        "pharma.specialite", "laboratory_id", string="Spécialités (titulaire AMM)"
    )
    pharma_specialite_count = fields.Integer(
        compute="_compute_pharma_specialite_count", string="Nb spécialités"
    )

    def _compute_pharma_specialite_count(self):
        data = self.env["pharma.specialite"]._read_group(
            [("laboratory_id", "in", self.ids)], ["laboratory_id"], ["__count"]
        )
        counts = {partner.id: count for partner, count in data}
        for partner in self:
            partner.pharma_specialite_count = counts.get(partner.id, 0)

    def action_view_pharma_specialites(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "pharma_fr_base.action_pharma_specialite"
        )
        action["domain"] = [("laboratory_id", "=", self.id)]
        action["context"] = {"default_laboratory_id": self.id}
        return action
