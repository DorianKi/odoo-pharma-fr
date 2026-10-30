"""Vues d'analyse (vues SQL en lecture seule, toujours à jour)."""

from odoo import fields, models, tools

CATEGORY_SELECTION = [
    ("drug_reimbursed", "Médicament remboursable"),
    ("drug_otc", "Médicament non remboursable"),
    ("parapharmacy", "Parapharmacie"),
    ("medical_device", "Dispositif médical (LPP)"),
    ("other", "Autre"),
]


class PharmaReportMixin(models.AbstractModel):
    _name = "pharma.report.mixin"
    _description = "Vue d'analyse SQL"
    _auto = False

    def _query(self):
        raise NotImplementedError

    def init(self):
        if self._abstract:
            return
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"CREATE OR REPLACE VIEW {self._table} AS ({self._query()})")


class PharmaPatientLoyalty(models.Model):
    """F. Fidélité de la patientèle : fréquence, panier, ancienneté et statut."""

    _name = "pharma.patient.loyalty"
    _inherit = "pharma.report.mixin"
    _description = "Fidélité des patients"
    _auto = False
    _order = "total_spent desc"

    patient_id = fields.Many2one("res.partner", "Patient", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    first_visit = fields.Date("Première visite", readonly=True)
    last_visit = fields.Date("Dernière visite", readonly=True)
    visit_count = fields.Integer("Passages", readonly=True)
    rx_count = fields.Integer("Ordonnances", readonly=True)
    total_spent = fields.Monetary("Total TTC", readonly=True)
    avg_basket = fields.Monetary("Panier moyen", readonly=True)
    is_chronic = fields.Boolean("Patient chronique", readonly=True)
    days_since_last = fields.Integer("Jours depuis la dernière visite", readonly=True)
    status = fields.Selection(
        [("new", "Nouveau (30 j)"), ("active", "Actif"), ("at_risk", "À risque"),
         ("lost", "Perdu")],
        string="Statut", readonly=True,
        help="Chronique : à risque après 40 jours sans visite, perdu après 60 jours. "
             "Autres patients : perdus après 120 jours.",
    )

    def _query(self):
        return """
            SELECT p.id AS id, p.id AS patient_id, MIN(rx.company_id) AS company_id,
                   MIN(rx.dispensing_date)::date AS first_visit,
                   MAX(rx.dispensing_date)::date AS last_visit,
                   COUNT(*) AS visit_count,
                   COUNT(rx.prescriber_id) AS rx_count,
                   SUM(rx.amount_total) AS total_spent,
                   AVG(rx.amount_total) AS avg_basket,
                   BOOL_OR(rx.renewal_index > 0) AS is_chronic,
                   (CURRENT_DATE - MAX(rx.dispensing_date)::date) AS days_since_last,
                   CASE
                     WHEN MIN(rx.dispensing_date)::date >= CURRENT_DATE - 30 THEN 'new'
                     WHEN BOOL_OR(rx.renewal_index > 0)
                          AND CURRENT_DATE - MAX(rx.dispensing_date)::date > 60 THEN 'lost'
                     WHEN BOOL_OR(rx.renewal_index > 0)
                          AND CURRENT_DATE - MAX(rx.dispensing_date)::date > 40 THEN 'at_risk'
                     WHEN CURRENT_DATE - MAX(rx.dispensing_date)::date > 120 THEN 'lost'
                     ELSE 'active'
                   END AS status
              FROM pharma_prescription rx
              JOIN res_partner p ON p.id = rx.patient_id
             WHERE rx.state IN ('done', 'returned')
               AND p.pharma_partner_type = 'patient'
               AND p.pharma_nir IS NOT NULL
          GROUP BY p.id
        """


class PharmaProductPerformance(models.Model):
    """H. Rentabilité par article et par mois : marge, classement ABC, rotation."""

    _name = "pharma.product.performance"
    _inherit = "pharma.report.mixin"
    _description = "Rentabilité des articles"
    _auto = False
    _order = "month desc, margin desc"

    month = fields.Date("Mois", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    product_id = fields.Many2one("product.product", "Article", readonly=True)
    product_tmpl_id = fields.Many2one("product.template", "Modèle", readonly=True)
    pharma_category = fields.Selection(CATEGORY_SELECTION, "Rayon", readonly=True)
    laboratory_id = fields.Many2one("res.partner", "Laboratoire", readonly=True)
    is_generic = fields.Boolean("Générique", readonly=True)
    quantity = fields.Float("Quantité vendue", readonly=True)
    revenue = fields.Monetary("CA HT", readonly=True)
    cost = fields.Monetary("Coût d'achat", readonly=True)
    margin = fields.Monetary("Marge brute (honoraires inclus)", readonly=True)
    margin_rate = fields.Float("Taux de marge (%)", readonly=True, digits=(12, 1))
    abc_class = fields.Selection([("A", "A (80 % de la marge)"), ("B", "B (15 %)"), ("C", "C (5 %)")],
                                 "Classe ABC", readonly=True)
    avg_stock_value = fields.Monetary("Stock moyen", readonly=True)
    gmroi = fields.Float("Marge / stock moyen", readonly=True, digits=(12, 2),
                         help="Rendement du stock : marge du mois rapportée au stock moyen.")

    def _query(self):
        return """
            WITH sales AS (
                SELECT l.product_id, l.company_id,
                       date_trunc('month', l.dispensing_date)::date AS month,
                       SUM(l.quantity) AS quantity, SUM(l.amount_untaxed) AS revenue,
                       SUM(l.amount_cost) AS cost, SUM(l.margin) AS margin
                  FROM pharma_prescription_line l
                 WHERE l.state = 'done'
              GROUP BY 1, 2, 3
            ), ranked AS (
                SELECT s.*,
                       SUM(s.margin) OVER (PARTITION BY s.company_id, s.month ORDER BY s.margin DESC
                                           ROWS UNBOUNDED PRECEDING)
                       / NULLIF(SUM(s.margin) OVER (PARTITION BY s.company_id, s.month), 0) AS cum_share
                  FROM sales s
            ), stock AS (
                SELECT product_id, company_id, date_trunc('month', date)::date AS month,
                       AVG(value) AS avg_stock_value
                  FROM pharma_stock_snapshot
              GROUP BY 1, 2, 3
            )
            SELECT row_number() OVER (ORDER BY r.month, r.product_id) AS id,
                   r.month, r.company_id, r.product_id, pp.product_tmpl_id,
                   pt.pharma_category, pt.pharma_laboratory_id AS laboratory_id,
                   COALESCE(pt.pharma_generic_type NOT IN ('princeps'), FALSE) AS is_generic,
                   r.quantity, r.revenue, r.cost, r.margin,
                   100.0 * r.margin / NULLIF(r.revenue, 0) AS margin_rate,
                   CASE WHEN r.cum_share <= 0.80 THEN 'A' WHEN r.cum_share <= 0.95 THEN 'B'
                        ELSE 'C' END AS abc_class,
                   st.avg_stock_value,
                   r.margin / NULLIF(st.avg_stock_value, 0) AS gmroi
              FROM ranked r
              JOIN product_product pp ON pp.id = r.product_id
              JOIN product_template pt ON pt.id = pp.product_tmpl_id
         LEFT JOIN stock st ON st.product_id = r.product_id AND st.company_id = r.company_id
                           AND st.month = r.month
        """


class PharmaPrescriberGenericReport(models.Model):
    """I. Substitution générique par prescripteur."""

    _name = "pharma.prescriber.generic.report"
    _inherit = "pharma.report.mixin"
    _description = "Génériques par prescripteur"
    _auto = False
    _order = "month desc, generic_rate"

    month = fields.Date("Mois", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    prescriber_id = fields.Many2one("res.partner", "Prescripteur", readonly=True)
    substitutable_lines = fields.Integer("Lignes substituables", readonly=True)
    generic_lines = fields.Integer("Lignes en générique", readonly=True)
    non_substitutable_lines = fields.Integer("Mentions « non substituable »", readonly=True)
    refused_lines = fields.Integer("Refus du patient", readonly=True)
    generic_rate = fields.Float("Taux de substitution (%)", readonly=True, digits=(12, 1))

    def _query(self):
        return """
            SELECT row_number() OVER (ORDER BY 1) AS id, x.*,
                   100.0 * x.generic_lines / NULLIF(x.substitutable_lines, 0) AS generic_rate
              FROM (
                SELECT date_trunc('month', rx.dispensing_date)::date AS month,
                       rx.company_id, rx.prescriber_id,
                       COUNT(*) AS substitutable_lines,
                       COUNT(*) FILTER (WHERE l.is_generic) AS generic_lines,
                       COUNT(*) FILTER (WHERE l.non_substitutable) AS non_substitutable_lines,
                       COUNT(*) FILTER (WHERE l.substitution_refused) AS refused_lines
                  FROM pharma_prescription_line l
                  JOIN pharma_prescription rx ON rx.id = l.prescription_id
                  JOIN product_template pt ON pt.id = l.product_tmpl_id
                 WHERE rx.state = 'done' AND rx.prescriber_id IS NOT NULL
                   AND pt.pharma_generic_group_id IS NOT NULL
              GROUP BY 1, 2, 3
              ) x
        """


class PharmaSellerReport(models.Model):
    """A. Performance de l'équipe par jour : passages, CA, panier moyen, marge."""

    _name = "pharma.seller.report"
    _inherit = "pharma.report.mixin"
    _description = "Performance de l'équipe"
    _auto = False
    _order = "day desc"

    day = fields.Date("Jour", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    seller_id = fields.Many2one("res.users", "Vendeur", readonly=True)
    visits = fields.Integer("Passages", readonly=True)
    rx_visits = fields.Integer("Ordonnances", readonly=True)
    counter_visits = fields.Integer("Ventes comptoir", readonly=True)
    revenue = fields.Monetary("CA TTC", readonly=True)
    avg_basket = fields.Monetary("Panier moyen TTC", readonly=True)
    margin = fields.Monetary("Marge brute HT", readonly=True)

    def _query(self):
        return """
            SELECT row_number() OVER (ORDER BY 1) AS id,
                   rx.dispensing_date::date AS day, rx.company_id, rx.seller_id,
                   COUNT(*) AS visits,
                   COUNT(rx.prescriber_id) AS rx_visits,
                   COUNT(*) - COUNT(rx.prescriber_id) AS counter_visits,
                   SUM(rx.amount_total) AS revenue,
                   AVG(rx.amount_total) AS avg_basket,
                   SUM(rx.margin) AS margin
              FROM pharma_prescription rx
             WHERE rx.state = 'done'
          GROUP BY 2, 3, 4
        """
