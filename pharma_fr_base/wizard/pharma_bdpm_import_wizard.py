import base64
import io
import zipfile

from odoo import fields, models
from odoo.exceptions import UserError

from ..lib import bdpm

STATS_LABELS = [
    ("specialites_created", "Spécialités créées"),
    ("specialites_updated", "Spécialités mises à jour"),
    ("laboratories", "Laboratoires (titulaires AMM)"),
    ("generic_groups_created", "Groupes génériques créés"),
    ("specialites_generic_updated", "Spécialités rattachées à un groupe générique"),
    ("composition_lines", "Lignes de composition"),
    ("specialites_conditions_updated", "Spécialités : conditions de prescription mises à jour"),
    ("mitm", "Médicaments d'intérêt thérapeutique majeur"),
    ("availability_events", "Ruptures / tensions signalées"),
    ("presentations_created", "Présentations créées"),
    ("presentations_updated", "Présentations mises à jour"),
    ("presentations_skipped", "Présentations ignorées (spécialité inconnue)"),
    ("products_created", "Articles officine créés ou reliés"),
]


class PharmaBdpmImportWizard(models.TransientModel):
    _name = "pharma.bdpm.import.wizard"
    _description = "Assistant d'import BDPM"

    zip_file = fields.Binary(
        "Archive ZIP",
        help="Archive contenant tout ou partie des fichiers BDPM (noms d'origine).",
    )
    zip_filename = fields.Char()
    cis_file = fields.Binary("Spécialités (CIS_bdpm.txt)")
    cis_filename = fields.Char()
    cis_cip_file = fields.Binary("Présentations (CIS_CIP_bdpm.txt)")
    cis_cip_filename = fields.Char()
    compo_file = fields.Binary("Compositions (CIS_COMPO_bdpm.txt)")
    compo_filename = fields.Char()
    gener_file = fields.Binary("Groupes génériques (CIS_GENER_bdpm.txt)")
    gener_filename = fields.Char()
    cpd_file = fields.Binary("Conditions de prescription (CIS_CPD_bdpm.txt)")
    cpd_filename = fields.Char()
    dispo_file = fields.Binary("Ruptures de stock (CIS_CIP_Dispo_Spec.txt)")
    dispo_filename = fields.Char()
    mitm_file = fields.Binary("MITM (CIS_MITM.txt)")
    mitm_filename = fields.Char()

    create_products = fields.Selection(
        [
            ("none", "Ne pas créer d'articles"),
            ("marketed_reimbursed", "Présentations commercialisées et remboursables"),
            ("marketed", "Toutes les présentations commercialisées"),
        ],
        string="Création des articles officine",
        default="none",
        required=True,
        help="Les présentations réservées à l'usage hospitalier sont exclues.",
    )
    product_limit = fields.Integer(
        "Nombre maximum d'articles", default=0, help="0 = pas de limite."
    )
    state = fields.Selection([("draft", "Paramètres"), ("done", "Terminé")], default="draft")
    result = fields.Text("Résultat", readonly=True)

    def _collect_files(self):
        files = {}
        if self.zip_file:
            try:
                archive = zipfile.ZipFile(io.BytesIO(base64.b64decode(self.zip_file)))
            except zipfile.BadZipFile as exc:
                raise UserError("L'archive fournie n'est pas un fichier ZIP valide.") from exc
            for name in archive.namelist():
                key = bdpm.file_key(name)
                if key:
                    files[key] = archive.read(name)
        for key in bdpm.FILE_KEYS.values():
            content = self[f"{key}_file"]
            if content:
                files[key] = base64.b64decode(content)
        return files

    def action_import(self):
        self.ensure_one()
        files = self._collect_files()
        if not files:
            raise UserError("Ajoutez au moins un fichier BDPM ou une archive ZIP.")
        stats = self.env["pharma.bdpm.importer"].import_files(
            files, self.create_products, self.product_limit
        )
        lines = [f"Fichiers traités : {', '.join(sorted(files))}", ""]
        lines += [f"{label} : {stats[key]}" for key, label in STATS_LABELS if key in stats]
        lines += [
            "",
            "Source : base de données publique des médicaments "
            "(https://base-donnees-publique.medicaments.gouv.fr).",
        ]
        self.write({"state": "done", "result": "\n".join(lines)})
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
