from odoo import api, fields, models

GENERIC_TYPE_SELECTION = [
    ("princeps", "Princeps"),
    ("generic", "Générique"),
    ("generic_posology", "Générique (complémentarité posologique)"),
    ("generic_substitutable", "Générique substituable"),
]

PRESCRIPTION_LIST_SELECTION = [
    ("none", "Non listé"),
    ("list_2", "Liste II"),
    ("list_1", "Liste I"),
    ("narcotic", "Stupéfiant"),
]

AVAILABILITY_SELECTION = [
    ("available", "Disponible"),
    ("tension", "Tension d'approvisionnement"),
    ("shortage", "Rupture de stock"),
    ("discontinued", "Arrêt de commercialisation"),
    ("restored", "Remise à disposition"),
]


class PharmaSpecialite(models.Model):
    """Spécialité pharmaceutique identifiée par son code CIS (fichier CIS_bdpm)."""

    _name = "pharma.specialite"
    _description = "Spécialité pharmaceutique (CIS)"
    _order = "name"
    _rec_names_search = ["name", "cis_code", "active_substances"]

    cis_code = fields.Char("Code CIS", required=True, index=True, size=8)
    name = fields.Char("Dénomination", required=True, index="trigram")
    pharmaceutical_form = fields.Char("Forme pharmaceutique")
    administration_routes = fields.Char("Voies d'administration")
    amm_status = fields.Char("Statut AMM")
    amm_procedure = fields.Char("Procédure AMM")
    amm_date = fields.Date("Date d'AMM")
    marketing_status = fields.Char("État de commercialisation")
    is_marketed = fields.Boolean(
        "Commercialisée", compute="_compute_is_marketed", store=True, index=True
    )
    bdm_status = fields.Char(
        "Statut BDM", help="« Alerte » ou « Warning disponibilité » dans la BDPM."
    )
    eu_authorisation_number = fields.Char("N° autorisation européenne")
    holder = fields.Char("Titulaire(s) AMM")
    laboratory_id = fields.Many2one(
        "res.partner",
        string="Laboratoire",
        index=True,
        domain=[("pharma_partner_type", "=", "laboratory")],
        help="Premier titulaire de l'AMM.",
    )
    reinforced_monitoring = fields.Boolean("Surveillance renforcée")

    # Génériques
    generic_group_id = fields.Many2one(
        "pharma.generic.group", string="Groupe générique", index=True
    )
    generic_type = fields.Selection(GENERIC_TYPE_SELECTION, string="Type générique")

    # Composition
    composition_ids = fields.One2many(
        "pharma.composition", "specialite_id", string="Composition"
    )
    active_substances = fields.Char(
        "Substances actives", compute="_compute_active_substances", store=True
    )

    # Prescription et délivrance
    prescription_conditions = fields.Text("Conditions de prescription / délivrance")
    prescription_list = fields.Selection(
        PRESCRIPTION_LIST_SELECTION, string="Liste", default="none", required=True,
        index=True,
    )
    narcotic_rules = fields.Boolean(
        "Règles des stupéfiants",
        help="Prescription sur ordonnance sécurisée (stupéfiants et assimilés).",
    )
    hospital_reserved = fields.Boolean("Réservé à l'usage hospitalier")
    special_prescription = fields.Boolean(
        "Prescription restreinte",
        help="Prescription hospitalière, initiale hospitalière ou réservée à "
             "certains spécialistes.",
    )

    # Disponibilité (ANSM) et MITM
    availability_status = fields.Selection(
        AVAILABILITY_SELECTION, string="Disponibilité nationale", default="available",
        required=True, index=True,
    )
    availability_date = fields.Date("Début de l'événement")
    availability_restore_date = fields.Date("Date de remise à disposition")
    availability_url = fields.Char("Lien ANSM")
    is_mitm = fields.Boolean(
        "MITM", help="Médicament d'intérêt thérapeutique majeur."
    )
    atc_code = fields.Char("Code ATC", index=True)

    presentation_ids = fields.One2many(
        "pharma.presentation", "specialite_id", string="Présentations"
    )
    presentation_count = fields.Integer(compute="_compute_presentation_count")

    _cis_code_uniq = models.Constraint(
        "unique (cis_code)", "Ce code CIS existe déjà."
    )

    @api.depends("marketing_status")
    def _compute_is_marketed(self):
        for spec in self:
            status = (spec.marketing_status or "").lower()
            spec.is_marketed = status.startswith("commercialis")

    @api.depends("composition_ids.substance_name", "composition_ids.nature")
    def _compute_active_substances(self):
        for spec in self:
            lines = spec.composition_ids.filtered(lambda c: c.nature == "SA")
            names = []
            for name in lines.mapped("substance_name"):
                if name and name not in names:
                    names.append(name)
            spec.active_substances = ", ".join(names)

    def _compute_presentation_count(self):
        data = self.env["pharma.presentation"]._read_group(
            [("specialite_id", "in", self.ids)], ["specialite_id"], ["__count"]
        )
        counts = {spec.id: count for spec, count in data}
        for spec in self:
            spec.presentation_count = counts.get(spec.id, 0)

    @api.depends("name", "cis_code")
    def _compute_display_name(self):
        for spec in self:
            spec.display_name = spec.name or spec.cis_code

    def action_view_presentations(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "pharma_fr_base.action_pharma_presentation"
        )
        action["domain"] = [("specialite_id", "=", self.id)]
        action["context"] = {"default_specialite_id": self.id}
        return action
