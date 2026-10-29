import re
from datetime import date

from odoo import api, fields, models
from odoo.exceptions import ValidationError


def nir_is_valid(nir):
    """Contrôle d'un numéro de sécurité sociale (NIR) à 15 caractères.

    Clé = 97 - (13 premiers chiffres modulo 97), les départements corses 2A et
    2B étant remplacés par 19 et 18 pour le calcul.

    >>> nir_is_valid("1 85 05 78 006 084 91")
    True
    >>> nir_is_valid("185057800608436")
    False
    >>> nir_is_valid("2 90 02 2A 123 456 78")
    True
    """
    value = re.sub(r"\s", "", nir or "").upper()
    if not re.fullmatch(r"[1-478]\d{4}(\d{2}|2A|2B)\d{6}\d{2}", value):
        return False
    body, key = value[:13], int(value[13:])
    body = body.replace("2A", "19", 1) if body[5:7] == "2A" else body
    body = body.replace("2B", "18", 1) if body[5:7] == "2B" else body
    return 97 - int(body) % 97 == key


class ResPartner(models.Model):
    _inherit = "res.partner"

    pharma_partner_type = fields.Selection(
        selection_add=[
            ("patient", "Patient"),
            ("prescriber", "Prescripteur"),
            ("insurer", "Organisme payeur"),
        ],
        ondelete={"patient": "set null", "prescriber": "set null", "insurer": "set null"},
    )

    # Patient
    pharma_birthdate = fields.Date("Date de naissance")
    pharma_age = fields.Integer("Âge", compute="_compute_pharma_age")
    pharma_nir = fields.Char("N° de sécurité sociale (NIR)", size=21)
    pharma_amo_id = fields.Many2one(
        "res.partner", string="Caisse d'assurance maladie (AMO)",
        domain=[("pharma_insurer_type", "=", "amo")],
    )
    pharma_amc_id = fields.Many2one(
        "res.partner", string="Complémentaire santé (AMC)",
        domain=[("pharma_insurer_type", "=", "amc")],
    )
    pharma_amc_coverage = fields.Selection(
        [
            ("none", "Aucune prise en charge"),
            ("tm", "Ticket modérateur"),
            ("tm_except_15", "Ticket modérateur sauf médicaments à 15 %"),
        ],
        string="Garantie complémentaire", default="tm",
    )
    pharma_exemption = fields.Selection(
        [
            ("none", "Aucune"),
            ("ald", "Affection de longue durée (ALD)"),
            ("c2s", "Complémentaire santé solidaire (C2S)"),
        ],
        string="Exonération du ticket modérateur", default="none",
        help="ALD : 100 % pour les médicaments en rapport avec l'affection "
             "(partie haute de l'ordonnance bizone). C2S : prise en charge intégrale.",
    )
    pharma_tiers_payant = fields.Boolean(
        "Tiers payant", default=True,
        help="Le patient ne règle que la part restant à sa charge.",
    )

    # Prescripteur
    pharma_rpps = fields.Char("N° RPPS", size=11)
    pharma_specialty = fields.Char("Spécialité médicale")

    # Organisme payeur
    pharma_insurer_type = fields.Selection(
        [("amo", "Assurance maladie obligatoire"), ("amc", "Complémentaire santé")],
        string="Type d'organisme",
    )
    pharma_insurer_code = fields.Char("N° d'organisme")

    @api.depends("pharma_birthdate")
    def _compute_pharma_age(self):
        for partner in self:
            partner.pharma_age = partner._pharma_age_at(date.today())

    def _pharma_age_at(self, on_date):
        self.ensure_one()
        birth = self.pharma_birthdate
        if not birth:
            return 0
        return on_date.year - birth.year - ((on_date.month, on_date.day) < (birth.month, birth.day))

    @api.constrains("pharma_nir")
    def _check_pharma_nir(self):
        for partner in self:
            if partner.pharma_nir and not nir_is_valid(partner.pharma_nir):
                raise ValidationError(
                    f"Numéro de sécurité sociale invalide pour {partner.display_name} "
                    "(format ou clé de contrôle)."
                )

    @api.constrains("pharma_rpps")
    def _check_pharma_rpps(self):
        for partner in self:
            if partner.pharma_rpps and not re.fullmatch(r"\d{11}", partner.pharma_rpps):
                raise ValidationError("Le numéro RPPS comporte 11 chiffres.")
