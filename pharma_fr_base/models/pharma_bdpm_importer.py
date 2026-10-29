"""Import / mise à jour du référentiel médicament depuis les fichiers BDPM.

L'import est idempotent : il peut être relancé à chaque publication de la BDPM.
Les enregistrements existants ne sont réécrits que si une valeur a changé, et
les écritures identiques sont regroupées pour limiter le nombre de requêtes.
"""

import logging
import os
from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import split_every

from ..lib import bdpm

_logger = logging.getLogger(__name__)

BATCH_SIZE = 1000

SPEC_FIELDS = [
    "name", "pharmaceutical_form", "administration_routes", "amm_status",
    "amm_procedure", "marketing_status", "amm_date", "bdm_status",
    "eu_authorisation_number", "holder", "reinforced_monitoring",
]
PRES_FIELDS = [
    "cip7", "name", "admin_status", "marketing_status", "marketing_date",
    "community_approval", "reimbursement_rate", "reimbursement_rates_raw",
    "price_ttc", "price_with_fees", "dispensing_fee", "reimbursement_indications",
]


class PharmaBdpmImporter(models.AbstractModel):
    _name = "pharma.bdpm.importer"
    _description = "Import de la Base de Données Publique des Médicaments"

    # ------------------------------------------------------------------
    # Points d'entrée
    # ------------------------------------------------------------------

    @api.model
    def import_files(self, files, create_products="none", product_limit=0):
        """Importe un ensemble de fichiers BDPM.

        :param files: dict {clé: contenu bytes}, clés de ``bdpm.FILE_KEYS``
            ('cis', 'cis_cip', 'compo', 'gener', 'cpd', 'dispo', 'mitm').
            Les fichiers absents sont simplement ignorés ; pour une première
            importation, 'cis' (spécialités) est indispensable.
        :param create_products: 'none', 'marketed' (toutes les présentations
            commercialisées) ou 'marketed_reimbursed' (remboursables seulement).
        :param product_limit: nombre maximum d'articles à créer (0 = illimité).
        :return: dict de statistiques.
        """
        if not self.env.user.has_group("pharma_fr_base.group_pharma_manager"):
            raise UserError("L'import BDPM est réservé au pharmacien titulaire.")
        self = self.with_context(
            tracking_disable=True, mail_create_nolog=True, active_test=False
        )
        unknown = set(files) - set(bdpm.FILE_KEYS.values())
        if unknown:
            raise UserError(f"Fichiers BDPM non reconnus : {', '.join(sorted(unknown))}")
        if not files:
            raise UserError("Aucun fichier BDPM fourni.")

        stats = defaultdict(int)
        if "cis" in files:
            self._import_specialites(files["cis"], stats)
        spec_map = self._spec_map()
        if not spec_map:
            raise UserError(
                "Aucune spécialité en base : importez d'abord le fichier "
                "CIS_bdpm.txt (spécialités)."
            )
        if "gener" in files:
            self._import_generic_groups(files["gener"], spec_map, stats)
        if "compo" in files:
            self._import_compositions(files["compo"], spec_map, stats)
        if "cpd" in files:
            self._import_conditions(files["cpd"], spec_map, stats)
        if "mitm" in files:
            self._import_mitm(files["mitm"], spec_map, stats)
        if "dispo" in files:
            self._import_availability(files["dispo"], spec_map, stats)
        if "cis_cip" in files:
            self._import_presentations(files["cis_cip"], spec_map, stats)
        if create_products and create_products != "none":
            products = self._create_products(create_products, product_limit)
            stats["products_created"] = len(products)
        self.env["ir.config_parameter"].sudo().set_param(
            "pharma_fr_base.bdpm_last_import", fields.Datetime.to_string(fields.Datetime.now())
        )
        _logger.info("Import BDPM terminé : %s", dict(stats))
        return dict(stats)

    @api.model
    def read_directory(self, path):
        """Lit les fichiers BDPM d'un répertoire -> dict {clé: bytes}."""
        if not path or not os.path.isdir(path):
            raise UserError(f"Répertoire BDPM introuvable : {path}")
        files = {}
        for filename in sorted(os.listdir(path)):
            key = bdpm.file_key(filename)
            if key:
                with open(os.path.join(path, filename), "rb") as fh:
                    files[key] = fh.read()
        return files

    @api.model
    def import_directory(self, path, create_products="none", product_limit=0):
        return self.import_files(self.read_directory(path), create_products, product_limit)

    @api.model
    def _cron_import_directory(self):
        """Tâche planifiée : met à jour la base depuis le répertoire configuré
        (paramètre système ``pharma_fr_base.bdpm_directory``)."""
        path = self.env["ir.config_parameter"].sudo().get_param(
            "pharma_fr_base.bdpm_directory"
        )
        if not path:
            _logger.warning("Import BDPM planifié : paramètre "
                            "pharma_fr_base.bdpm_directory non défini.")
            return
        manager = self.env.ref("base.user_root")
        self.with_user(manager).import_directory(path)

    # ------------------------------------------------------------------
    # Étapes
    # ------------------------------------------------------------------

    def _spec_map(self):
        Spec = self.env["pharma.specialite"]
        return {r["cis_code"]: r["id"] for r in Spec.search_read([], ["cis_code"])}

    def _import_specialites(self, content, stats):
        Spec = self.env["pharma.specialite"]
        data = bdpm.parse_specialites(content)
        labs = self._get_laboratories(
            {v["main_holder"] for v in data.values() if v["main_holder"]}
        )
        new_values = {}
        for cis, vals in data.items():
            values = {f: vals[f] for f in SPEC_FIELDS}
            values["laboratory_id"] = labs.get(vals["main_holder"].upper(), False)
            new_values[cis] = values
        created, updated = self._upsert(
            Spec, "cis_code", new_values, SPEC_FIELDS + ["laboratory_id"]
        )
        stats["specialites_created"] += created
        stats["specialites_updated"] += updated
        stats["laboratories"] = len(labs)

    def _import_generic_groups(self, content, spec_map, stats):
        Group = self.env["pharma.generic.group"]
        groups, members = bdpm.parse_generic_groups(content)
        created, _updated = self._upsert(
            Group, "code", {code: {"name": label} for code, label in groups.items()},
            ["name"],
        )
        stats["generic_groups_created"] += created
        group_map = {r["code"]: r["id"] for r in Group.search_read([], ["code"])}
        targets = {}
        for cis, spec_id in spec_map.items():
            member = members.get(cis)
            targets[spec_id] = {
                "generic_group_id": group_map.get(member["group_code"], False) if member else False,
                "generic_type": member["generic_type"] if member else False,
            }
        stats["specialites_generic_updated"] += self._write_changes(
            self.env["pharma.specialite"], targets
        )

    def _import_compositions(self, content, spec_map, stats):
        Compo = self.env["pharma.composition"]
        data = bdpm.parse_compositions(content)
        spec_ids = [spec_map[cis] for cis in data if cis in spec_map]
        for ids in split_every(BATCH_SIZE, spec_ids):
            Compo.search([("specialite_id", "in", list(ids))]).unlink()
        vals_list = [
            dict(line, specialite_id=spec_map[cis])
            for cis, lines in data.items() if cis in spec_map
            for line in lines
        ]
        for batch in split_every(BATCH_SIZE, vals_list):
            Compo.create(list(batch))
        stats["composition_lines"] += len(vals_list)

    def _import_conditions(self, content, spec_map, stats):
        data = bdpm.parse_conditions(content)
        targets = {}
        for cis, spec_id in spec_map.items():
            conditions = data.get(cis, [])
            values = bdpm.classify_conditions(conditions)
            values["prescription_conditions"] = "\n".join(conditions) or False
            targets[spec_id] = values
        stats["specialites_conditions_updated"] += self._write_changes(
            self.env["pharma.specialite"], targets
        )

    def _import_mitm(self, content, spec_map, stats):
        data = bdpm.parse_mitm(content)
        targets = {
            spec_id: {"is_mitm": cis in data, "atc_code": data.get(cis) or False}
            for cis, spec_id in spec_map.items()
        }
        stats["mitm"] = sum(1 for cis in data if cis in spec_map)
        self._write_changes(self.env["pharma.specialite"], targets)

    def _import_availability(self, content, spec_map, stats):
        data = bdpm.parse_availability(content)
        targets = {}
        for cis, spec_id in spec_map.items():
            entry = data.get(cis)
            targets[spec_id] = {
                "availability_status": entry["availability_status"] if entry else "available",
                "availability_date": entry["availability_date"] if entry else False,
                "availability_restore_date": (
                    entry["availability_restore_date"] if entry else False
                ),
                "availability_url": entry["availability_url"] if entry else False,
            }
        stats["availability_events"] = sum(1 for cis in data if cis in spec_map)
        self._write_changes(self.env["pharma.specialite"], targets)

    def _import_presentations(self, content, spec_map, stats):
        Pres = self.env["pharma.presentation"]
        data = bdpm.parse_presentations(content)
        new_values = {}
        for cip13, vals in data.items():
            spec_id = spec_map.get(vals["cis_code"])
            if not spec_id:
                stats["presentations_skipped"] += 1
                continue
            values = {f: vals[f] for f in PRES_FIELDS}
            values["specialite_id"] = spec_id
            new_values[cip13] = values
        created, updated = self._upsert(
            Pres, "cip13", new_values, PRES_FIELDS + ["specialite_id"]
        )
        stats["presentations_created"] += created
        stats["presentations_updated"] += updated

    def _create_products(self, mode, limit=0):
        domain = [
            ("product_tmpl_id", "=", False),
            ("is_marketed", "=", True),
            ("specialite_id.hospital_reserved", "=", False),
        ]
        if mode == "marketed_reimbursed":
            domain.append(("is_reimbursable", "=", True))
        presentations = self.env["pharma.presentation"].search(
            domain, order="cip13", limit=limit or None
        )
        products = self.env["product.template"]
        for batch in split_every(BATCH_SIZE, presentations.ids):
            products |= self.env["pharma.presentation"].browse(batch)._create_products()
        return products

    # ------------------------------------------------------------------
    # Outils
    # ------------------------------------------------------------------

    def _get_laboratories(self, names):
        """Renvoie {NOM EN MAJUSCULES: partner_id}, en créant les laboratoires
        manquants (partenaires société de type « Laboratoire »)."""
        Partner = self.env["res.partner"]
        result = {}
        upper_names = {n.upper(): n for n in names}
        if not upper_names:
            return result
        existing = Partner.search([
            ("is_company", "=", True),
            ("name", "in", list(names)),
        ])
        for partner in existing:
            result.setdefault(partner.name.upper(), partner.id)
        to_fix = existing.filtered(lambda p: not p.pharma_partner_type)
        if to_fix:
            to_fix.pharma_partner_type = "laboratory"
        missing = [name for key, name in upper_names.items() if key not in result]
        for batch in split_every(BATCH_SIZE, missing):
            for partner in Partner.create([
                {"name": name, "is_company": True, "pharma_partner_type": "laboratory"}
                for name in batch
            ]):
                result[partner.name.upper()] = partner.id
        return result

    def _upsert(self, model, key_field, new_values, compared_fields):
        """Crée ou met à jour des enregistrements identifiés par ``key_field``.

        :return: (nb créés, nb modifiés)
        """
        existing = {
            rec[key_field]: rec
            for rec in model.search_read(
                [(key_field, "in", list(new_values))], [key_field] + compared_fields
            )
        }
        to_create, targets = [], {}
        for key, values in new_values.items():
            if key in existing:
                targets[existing[key]["id"]] = values
            else:
                to_create.append(dict(values, **{key_field: key}))
        for batch in split_every(BATCH_SIZE, to_create):
            model.create(list(batch))
        updated = self._write_changes(model, targets, current={
            rec["id"]: rec for rec in existing.values()
        })
        return len(to_create), updated

    def _write_changes(self, model, targets, current=None):
        """Écrit ``targets`` ({id: valeurs}) en ignorant les valeurs inchangées.

        Les enregistrements recevant exactement les mêmes modifications sont
        écrits en une seule fois.
        :return: nombre d'enregistrements modifiés.
        """
        if not targets:
            return 0
        names = sorted({f for values in targets.values() for f in values})
        if current is None:
            current = {}
            for ids in split_every(BATCH_SIZE * 5, list(targets)):
                for rec in model.browse(ids).read(names):
                    current[rec["id"]] = rec
        groups = defaultdict(list)
        for rec_id, values in targets.items():
            old = current.get(rec_id, {})
            changes = {
                f: v for f, v in values.items()
                if self._normalize(old.get(f)) != self._normalize(v)
            }
            if changes:
                groups[tuple(sorted(changes.items(), key=lambda i: i[0]))].append(rec_id)
        for frozen, ids in groups.items():
            for batch in split_every(BATCH_SIZE, ids):
                model.browse(batch).write(dict(frozen))
        return sum(len(ids) for ids in groups.values())

    @staticmethod
    def _normalize(value):
        """Rend comparables les valeurs lues (read) et les valeurs à écrire."""
        if isinstance(value, tuple) and len(value) == 2:  # many2one lu
            return value[0]
        if isinstance(value, float):
            return round(value, 4)
        if value in (None, "", False):
            return False
        return value
