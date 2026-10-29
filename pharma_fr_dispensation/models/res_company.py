from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    pharma_invoicing_mode = fields.Selection(
        [
            ("per_prescription", "Une facture par payeur et par ordonnance"),
            ("daily", "Bordereaux journaliers par payeur"),
        ],
        string="Facturation des délivrances", default="per_prescription", required=True,
        help="Bordereaux journaliers : chaque jour, une facture par organisme (AMO, AMC) "
             "regroupant les ordonnances de la journée, comme les lots de télétransmission.",
    )
    pharma_counter_partner_id = fields.Many2one(
        "res.partner", string="Client « encaissements comptoir »",
        help="En mode journalier, les parts réglées par les patients sont regroupées "
             "sur ce client (équivalent du ticket Z de caisse). Vide : une facture par patient.",
    )
