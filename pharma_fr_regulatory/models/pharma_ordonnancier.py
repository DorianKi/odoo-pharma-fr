from odoo import api, fields, models
from odoo.exceptions import UserError

LISTED = ("list_1", "list_2", "narcotic")


class PharmaOrdonnancier(models.Model):
    """Ordonnancier (art. R. 5132-10 du code de la santé publique).

    Transcription chronologique et numérotée des délivrances de médicaments
    listés (liste I, liste II, stupéfiants) : patient, prescripteur, produit et
    quantité. Les informations sont figées au moment de la délivrance.
    """

    _name = "pharma.ordonnancier"
    _description = "Ordonnancier"
    _order = "number desc"
    _rec_name = "number"

    number = fields.Char("N° d'ordre", required=True, readonly=True, index=True)
    company_id = fields.Many2one("res.company", required=True, readonly=True, index=True)
    date = fields.Datetime("Date de délivrance", required=True, readonly=True, index=True)
    prescription_id = fields.Many2one("pharma.prescription", "Ordonnance", readonly=True,
                                      index=True)
    prescription_date = fields.Date("Date de prescription", readonly=True)
    patient_id = fields.Many2one("res.partner", "Patient", readonly=True, index=True)
    patient_name = fields.Char("Nom du patient", readonly=True)
    patient_address = fields.Char("Adresse du patient", readonly=True)
    prescriber_id = fields.Many2one("res.partner", "Prescripteur", readonly=True)
    prescriber_name = fields.Char("Nom du prescripteur", readonly=True)
    prescriber_rpps = fields.Char("RPPS", readonly=True)
    product_id = fields.Many2one("product.product", "Médicament", readonly=True)
    product_name = fields.Char("Désignation", readonly=True)
    quantity = fields.Float("Quantité", readonly=True)
    prescription_list = fields.Selection(
        [("list_1", "Liste I"), ("list_2", "Liste II"), ("narcotic", "Stupéfiant")],
        string="Liste", readonly=True,
    )
    lot_names = fields.Char("Lots", readonly=True)

    _number_uniq = models.Constraint(
        "unique (company_id, number)", "Ce numéro d'ordonnancier existe déjà."
    )

    @api.model
    def _record_prescription(self, prescription):
        """Inscrit les lignes listées d'une ordonnance délivrée."""
        lines = prescription.line_ids.filtered(
            lambda line: line.product_id.pharma_prescription_list in LISTED
        )
        patient, prescriber = prescription.patient_id, prescription.prescriber_id
        address = ", ".join(filter(None, [patient.street, patient.zip, patient.city]))
        vals_list = []
        for line in lines:
            vals_list.append({
                "number": self.env["ir.sequence"].with_company(prescription.company_id)
                .next_by_code("pharma.ordonnancier"),
                "company_id": prescription.company_id.id,
                "date": prescription.dispensing_date,
                "prescription_id": prescription.id,
                "prescription_date": prescription.prescription_date,
                "patient_id": patient.id,
                "patient_name": patient.name,
                "patient_address": address,
                "prescriber_id": prescriber.id,
                "prescriber_name": prescriber.name,
                "prescriber_rpps": prescriber.pharma_rpps,
                "product_id": line.product_id.id,
                "product_name": line.product_id.display_name,
                "quantity": line.quantity,
                "prescription_list": line.product_id.pharma_prescription_list,
                "lot_names": line.lot_names,
            })
        return self.sudo().create(vals_list)

    def write(self, vals):
        raise UserError("L'ordonnancier ne peut pas être modifié.")

    def unlink(self):
        raise UserError("L'ordonnancier ne peut pas être supprimé.")
