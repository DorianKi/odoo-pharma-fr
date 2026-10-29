from odoo import api, fields, models

CAP_CATEGORY_SELECTION = [
    ("base", "Spécialités remboursables (cas général)"),
    ("generic", "Génériques (et assimilés)"),
    ("biosimilar", "Biosimilaires substituables"),
]


class PharmaDiscountCap(models.Model):
    """Plafond légal des avantages commerciaux consentis aux officines.

    Article L. 138-9 du code de la sécurité sociale : les remises, ristournes et
    avantages de toute nature sur les spécialités remboursables sont plafonnés
    (en % du prix fabricant HT), avec des plafonds relevés par arrêté pour les
    génériques et les biosimilaires. Ces plafonds évoluent : ils sont datés pour
    que chaque commande applique celui en vigueur à sa date.
    """

    _name = "pharma.discount.cap"
    _description = "Plafond légal de remise (art. L. 138-9 CSS)"
    _order = "cap_category, date_from desc"

    name = fields.Char("Libellé", required=True)
    cap_category = fields.Selection(
        CAP_CATEGORY_SELECTION, string="Catégorie", required=True
    )
    rate = fields.Float("Plafond (%)", required=True, digits=(5, 2))
    date_from = fields.Date("En vigueur à partir du", required=True)
    source = fields.Char("Texte de référence")
    active = fields.Boolean(default=True)

    _rate_check = models.Constraint(
        "CHECK (rate >= 0 AND rate <= 100)", "Le plafond doit être compris entre 0 et 100 %."
    )

    @api.model
    def _get_rate(self, category, date=None):
        """Plafond (en %) en vigueur à ``date`` pour ``category``, ou None si
        la catégorie n'est pas plafonnée (produit à prix libre)."""
        if not category or category == "none":
            return None
        date = date or fields.Date.context_today(self)
        cap = self.search(
            [("cap_category", "=", category), ("date_from", "<=", date)],
            order="date_from desc", limit=1,
        )
        return cap.rate if cap else None
