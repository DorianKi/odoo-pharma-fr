#!/usr/bin/env python3
"""Extraction des données d'Odoo vers des fichiers CSV prêts à charger dans BigQuery.

Première étape du flux : Odoo (PostgreSQL) → CSV pseudonymisés → BigQuery (pharma_raw)
→ dbt (staging, core, mart) → Looker Studio.

Pseudonymisation, avant que rien ne quitte le poste :
- aucun nom, NIR, adresse ni date de naissance complète de patient n'est exporté ;
- le patient devient une clé HMAC-SHA256 (clé secrète gardée sur le poste) : la même
  personne garde la même clé d'un export à l'autre, sans qu'on puisse remonter à elle ;
- seuls restent l'année de naissance, le code postal et le régime (ALD, C2S, mutuelle).

Usage (depuis la racine du dépôt) :

    python3 scripts/export_raw.py --dbname pharmacie2 --out export/

Connexion : options --host / --port / --user, mot de passe dans la variable PGPASSWORD
(par défaut localhost:55432, utilisateur odoo, celui du docker-compose).
Clé de pseudonymisation : variable PHARMA_PSEUDO_KEY, sinon fichier .pseudo_key créé au
premier lancement (non versionné). Changer de clé change toutes les clés patient.

Dépendance : psycopg2 (pip install psycopg2-binary).
"""
import argparse
import csv
import hashlib
import hmac
import json
import os
import secrets
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

# Chaque table brute : description, requête, colonnes (nom, type BigQuery, description).
# Les dates et heures sont exportées telles qu'Odoo les stocke, en UTC ; la conversion à
# l'heure de Paris se fait dans dbt (staging).
# Une colonne nommée « patient_id » est remplacée par « patient_key » (clé pseudonyme).
TABLES = {
    "prescription": {
        "description": "Passages en caisse : ordonnances et ventes au comptoir (une ligne par passage).",
        "sql": """
            SELECT rx.id, rx.name, rx.state, rx.patient_id, rx.prescriber_id, rx.seller_id,
                   rx.prescription_type, rx.renewal_index, rx.prescription_date,
                   rx.dispensing_date, rx.amount_total, rx.amount_amo, rx.amount_amc,
                   rx.amount_patient, rx.amount_fees, rx.amount_untaxed, rx.amount_cost,
                   rx.margin
              FROM pharma_prescription rx
             WHERE rx.state IN ('done', 'returned')
        """,
        "columns": [
            ("id", "INT64", "Identifiant du passage dans Odoo"),
            ("name", "STRING", "Référence"),
            ("state", "STRING", "done = délivré, returned = retourné"),
            ("patient_key", "STRING", "Patient (clé pseudonyme)"),
            ("prescriber_id", "INT64", "Prescripteur ; vide pour une vente au comptoir"),
            ("seller_id", "INT64", "Vendeur (utilisateur Odoo)"),
            ("prescription_type", "STRING", "standard, bizone, secure (sécurisée), exception"),
            ("renewal_index", "INT64", "Numéro de renouvellement (0 = première délivrance)"),
            ("prescription_date", "DATE", "Date de l'ordonnance"),
            ("dispensing_date", "TIMESTAMP", "Date et heure de délivrance (UTC)"),
            ("amount_total", "NUMERIC", "Total TTC, honoraires compris"),
            ("amount_amo", "NUMERIC", "Part Assurance maladie"),
            ("amount_amc", "NUMERIC", "Part complémentaire"),
            ("amount_patient", "NUMERIC", "Reste à charge du patient"),
            ("amount_fees", "NUMERIC", "Honoraires TTC"),
            ("amount_untaxed", "NUMERIC", "Total HT"),
            ("amount_cost", "NUMERIC", "Coût d'achat"),
            ("margin", "NUMERIC", "Marge brute HT, honoraires compris"),
        ],
    },
    "prescription_line": {
        "description": "Lignes délivrées (une ligne par article et par passage).",
        "sql": """
            SELECT l.id, l.prescription_id, l.state, l.product_id, l.prescribed_product_id,
                   l.quantity, l.ald_related, l.non_substitutable, l.substitution_refused,
                   l.is_substitution, l.is_generic, l.reimbursement_rate, l.unit_price,
                   l.vat_rate, l.tiers_payant, l.amount_total, l.amount_amo, l.amount_amc,
                   l.amount_patient, l.amount_untaxed, l.amount_fees_untaxed, l.amount_cost,
                   l.margin
              FROM pharma_prescription_line l
             WHERE l.state IN ('done', 'returned')
        """,
        "columns": [
            ("id", "INT64", "Identifiant de la ligne"),
            ("prescription_id", "INT64", "Passage"),
            ("state", "STRING", "done = délivré, returned = retourné"),
            ("product_id", "INT64", "Article délivré"),
            ("prescribed_product_id", "INT64", "Article prescrit, si différent (substitution)"),
            ("quantity", "INT64", "Boîtes"),
            ("ald_related", "BOOL", "En rapport avec une affection de longue durée"),
            ("non_substitutable", "BOOL", "Mention « non substituable » du prescripteur"),
            ("substitution_refused", "BOOL", "Le patient a refusé le générique"),
            ("is_substitution", "BOOL", "Le pharmacien a substitué un générique au princeps"),
            ("is_generic", "BOOL", "Article délivré générique"),
            ("reimbursement_rate", "INT64", "Taux de remboursement (%)"),
            ("unit_price", "NUMERIC", "Prix unitaire TTC"),
            ("vat_rate", "FLOAT64", "Taux de TVA (%)"),
            ("tiers_payant", "BOOL", "Tiers payant appliqué"),
            ("amount_total", "NUMERIC", "Total TTC"),
            ("amount_amo", "NUMERIC", "Part Assurance maladie"),
            ("amount_amc", "NUMERIC", "Part complémentaire"),
            ("amount_patient", "NUMERIC", "Part patient"),
            ("amount_untaxed", "NUMERIC", "Total HT (honoraires à la boîte compris)"),
            ("amount_fees_untaxed", "NUMERIC", "Honoraires à la boîte HT"),
            ("amount_cost", "NUMERIC", "Coût d'achat"),
            ("margin", "NUMERIC", "Marge brute HT"),
        ],
    },
    "product": {
        "description": "Articles vendus, achetés, stockés ou manquants.",
        "sql": """
            WITH used AS (
                SELECT product_id FROM pharma_prescription_line
                UNION SELECT product_id FROM pharma_stock_snapshot
                UNION SELECT product_id FROM purchase_order_line WHERE product_id IS NOT NULL
                UNION SELECT product_id FROM pharma_missing_item
            )
            SELECT pp.id, pt.pharma_cip13 AS cip13,
                   COALESCE(to_jsonb(pt.name)->>'fr_FR', to_jsonb(pt.name)->>'en_US', pt.name::text) AS name,
                   pt.pharma_category AS category, lab.name AS laboratory,
                   pt.pharma_generic_type AS generic_type,
                   COALESCE(to_jsonb(gg.name)->>'fr_FR', to_jsonb(gg.name)->>'en_US',
                            gg.name::text) AS generic_group,
                   pt.pharma_reimbursement_rate AS reimbursement_rate,
                   pt.pharma_vat_rate AS vat_rate, pt.pharma_public_price AS public_price,
                   pt.list_price, pt.pharma_is_narcotic AS is_narcotic,
                   pt.pharma_prescription_list AS prescription_list,
                   pt.pharma_availability_status AS availability_status,
                   COALESCE(pt.pharma_is_fee, FALSE) AS is_fee
              FROM used u
              JOIN product_product pp ON pp.id = u.product_id
              JOIN product_template pt ON pt.id = pp.product_tmpl_id
         LEFT JOIN res_partner lab ON lab.id = pt.pharma_laboratory_id
         LEFT JOIN pharma_generic_group gg ON gg.id = pt.pharma_generic_group_id
        """,
        "columns": [
            ("id", "INT64", "Identifiant de l'article"),
            ("cip13", "STRING", "Code CIP13 (médicaments)"),
            ("name", "STRING", "Libellé"),
            ("category", "STRING", "Rayon : drug_reimbursed, drug_otc, parapharmacy, medical_device, other"),
            ("laboratory", "STRING", "Laboratoire titulaire ou fournisseur"),
            ("generic_type", "STRING", "princeps, generic, … ; vide hors répertoire des génériques"),
            ("generic_group", "STRING", "Groupe générique (répertoire ANSM)"),
            ("reimbursement_rate", "STRING", "Taux de remboursement"),
            ("vat_rate", "STRING", "Taux de TVA"),
            ("public_price", "NUMERIC", "Prix public réglementé TTC"),
            ("list_price", "NUMERIC", "Prix de vente TTC (prix libre)"),
            ("is_narcotic", "BOOL", "Stupéfiant"),
            ("prescription_list", "STRING", "Liste I, liste II, stupéfiant…"),
            ("availability_status", "STRING", "Disponibilité nationale (tension, rupture…)"),
            ("is_fee", "BOOL", "Article d'honoraire, pas une marchandise"),
        ],
    },
    "patient": {
        "description": "Patients, pseudonymisés : ni nom, ni NIR, ni date de naissance.",
        "sql": """
            SELECT p.id AS patient_id, EXTRACT(YEAR FROM p.pharma_birthdate)::int AS birth_year,
                   p.zip, p.pharma_exemption AS exemption,
                   (p.pharma_amc_id IS NOT NULL) AS has_amc,
                   COALESCE(p.pharma_tiers_payant, FALSE) AS tiers_payant,
                   (p.pharma_nir IS NULL) AS is_anonymous
              FROM res_partner p
             WHERE p.pharma_partner_type = 'patient'
        """,
        "columns": [
            ("patient_key", "STRING", "Patient (clé pseudonyme)"),
            ("birth_year", "INT64", "Année de naissance"),
            ("zip", "STRING", "Code postal"),
            ("exemption", "STRING", "Exonération : none, ald, c2s…"),
            ("has_amc", "BOOL", "A une complémentaire santé"),
            ("tiers_payant", "BOOL", "Bénéficie du tiers payant"),
            ("is_anonymous", "BOOL", "Client de passage sans carte Vitale"),
        ],
    },
    "prescriber": {
        "description": "Prescripteurs (données professionnelles).",
        "sql": """
            SELECT p.id, p.name, p.pharma_rpps AS rpps, p.pharma_specialty AS specialty, p.zip
              FROM res_partner p WHERE p.pharma_partner_type = 'prescriber'
        """,
        "columns": [
            ("id", "INT64", "Identifiant"),
            ("name", "STRING", "Nom"),
            ("rpps", "STRING", "Numéro RPPS"),
            ("specialty", "STRING", "Spécialité"),
            ("zip", "STRING", "Code postal du cabinet"),
        ],
    },
    "staff": {
        "description": "Membres de l'équipe (utilisateurs Odoo).",
        "sql": """
            SELECT u.id, p.name, u.active FROM res_users u JOIN res_partner p ON p.id = u.partner_id
             WHERE u.share IS NOT TRUE
        """,
        "columns": [
            ("id", "INT64", "Identifiant"),
            ("name", "STRING", "Nom"),
            ("active", "BOOL", "Compte actif"),
        ],
    },
    "partner": {
        "description": "Fournisseurs (grossistes, laboratoires) et payeurs (Assurance maladie, mutuelles).",
        "sql": """
            SELECT p.id, p.name, p.pharma_partner_type AS partner_type,
                   p.pharma_insurer_type AS insurer_type,
                   p.pharma_payment_delay_days AS payment_delay_days,
                   p.pharma_franco_amount AS franco_amount,
                   COALESCE(p.pharma_is_main_wholesaler, FALSE) AS is_main_wholesaler
              FROM res_partner p
             WHERE p.pharma_partner_type IN ('wholesaler', 'laboratory', 'insurer')
                OR p.id IN (SELECT partner_id FROM purchase_order)
                OR p.id IN (SELECT pharma_counter_partner_id FROM res_company
                             WHERE pharma_counter_partner_id IS NOT NULL)
        """,
        "columns": [
            ("id", "INT64", "Identifiant"),
            ("name", "STRING", "Nom"),
            ("partner_type", "STRING", "wholesaler, laboratory, insurer"),
            ("insurer_type", "STRING", "amo (Assurance maladie) ou amc (complémentaire)"),
            ("payment_delay_days", "INT64", "Délai de paiement attendu (jours)"),
            ("franco_amount", "NUMERIC", "Franco de port (€ HT)"),
            ("is_main_wholesaler", "BOOL", "Grossiste principal"),
        ],
    },
    "purchase_line": {
        "description": "Lignes de commandes fournisseurs.",
        "sql": """
            SELECT l.id, o.id AS order_id, o.name AS order_name, o.origin, o.state,
                   o.partner_id, o.date_order, o.date_approve, l.product_id, l.product_qty,
                   l.qty_received, l.price_unit, l.discount, l.price_subtotal
              FROM purchase_order_line l
              JOIN purchase_order o ON o.id = l.order_id
             WHERE l.product_id IS NOT NULL AND l.display_type IS NULL
        """,
        "columns": [
            ("id", "INT64", "Identifiant de la ligne"),
            ("order_id", "INT64", "Commande"),
            ("order_name", "STRING", "Référence de la commande"),
            ("origin", "STRING", "Origine : réassort, dépannage, commande directe…"),
            ("state", "STRING", "État de la commande"),
            ("partner_id", "INT64", "Fournisseur"),
            ("date_order", "TIMESTAMP", "Date de commande (UTC)"),
            ("date_approve", "TIMESTAMP", "Date de confirmation (UTC)"),
            ("product_id", "INT64", "Article"),
            ("product_qty", "FLOAT64", "Quantité commandée"),
            ("qty_received", "FLOAT64", "Quantité reçue"),
            ("price_unit", "NUMERIC", "Prix unitaire HT avant remise"),
            ("discount", "FLOAT64", "Remise (%)"),
            ("price_subtotal", "NUMERIC", "Montant HT après remise"),
        ],
    },
    "invoice": {
        "description": "Factures clients (bordereaux AMO / AMC, comptoir) et fournisseurs, "
                       "avec leur date de paiement.",
        "sql": """
            WITH paid AS (
                SELECT ml.move_id, MAX(apr.max_date) AS paid_date
                  FROM account_move_line ml
                  JOIN account_account a ON a.id = ml.account_id
                  JOIN account_partial_reconcile apr
                    ON apr.debit_move_id = ml.id OR apr.credit_move_id = ml.id
                 WHERE a.account_type IN ('asset_receivable', 'liability_payable')
              GROUP BY ml.move_id
            )
            SELECT m.id, m.name, m.move_type, m.state, m.partner_id, m.invoice_date,
                   m.invoice_date_due, m.amount_total, m.amount_residual, m.payment_state,
                   CASE WHEN m.payment_state IN ('paid', 'in_payment') THEN paid.paid_date END
                       AS paid_date
              FROM account_move m
         LEFT JOIN paid ON paid.move_id = m.id
             WHERE m.move_type IN ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')
               AND m.state = 'posted'
        """,
        "columns": [
            ("id", "INT64", "Identifiant"),
            ("name", "STRING", "Numéro"),
            ("move_type", "STRING",
             "out_invoice, out_refund (clients) ; in_invoice, in_refund (fournisseurs)"),
            ("state", "STRING", "posted = comptabilisée"),
            ("partner_id", "INT64", "Payeur ou fournisseur"),
            ("invoice_date", "DATE", "Date de facture"),
            ("invoice_date_due", "DATE", "Échéance"),
            ("amount_total", "NUMERIC", "Montant TTC"),
            ("amount_residual", "NUMERIC", "Reste dû"),
            ("payment_state", "STRING", "not_paid, partial, in_payment, paid, reversed"),
            ("paid_date", "DATE", "Date du dernier règlement, si soldée"),
        ],
    },
    "cash_line": {
        "description": "Mouvements de trésorerie (banque et caisse).",
        "sql": """
            SELECT ml.id, ml.date, j.type AS journal_type, j.code AS journal_code,
                   ml.partner_id, ml.debit, ml.credit
              FROM account_move_line ml
              JOIN account_journal j ON j.id = ml.journal_id
              JOIN account_account a ON a.id = ml.account_id
             WHERE j.type IN ('bank', 'cash') AND ml.parent_state = 'posted'
               AND a.account_type NOT IN ('asset_receivable', 'liability_payable')
        """,
        "columns": [
            ("id", "INT64", "Identifiant de l'écriture"),
            ("date", "DATE", "Date"),
            ("journal_type", "STRING", "bank ou cash"),
            ("journal_code", "STRING", "Code du journal"),
            ("partner_id", "INT64", "Payeur ou fournisseur"),
            ("debit", "NUMERIC", "Entrée d'argent"),
            ("credit", "NUMERIC", "Sortie d'argent"),
        ],
    },
    "stock_snapshot": {
        "description": "Photo quotidienne du stock, par article (prise chaque soir).",
        "sql": """
            SELECT s.id, s.date, s.product_id, s.quantity, s.unit_cost, s.value, s.sales_30d,
                   s.daily_demand, s.coverage_days, s.qty_expiring_90d, s.value_expiring_90d,
                   s.qty_expired, s.last_sale_date, s.is_dormant, s.is_out_of_stock,
                   s.national_shortage
              FROM pharma_stock_snapshot s
        """,
        "columns": [
            ("id", "INT64", "Identifiant"),
            ("date", "DATE", "Jour de la photo"),
            ("product_id", "INT64", "Article"),
            ("quantity", "FLOAT64", "Quantité en stock"),
            ("unit_cost", "NUMERIC", "Coût unitaire"),
            ("value", "NUMERIC", "Valeur au coût"),
            ("sales_30d", "FLOAT64", "Ventes des 30 derniers jours"),
            ("daily_demand", "NUMERIC", "Demande moyenne par jour"),
            ("coverage_days", "NUMERIC", "Couverture en jours"),
            ("qty_expiring_90d", "FLOAT64", "Quantité qui périme sous 90 jours"),
            ("value_expiring_90d", "NUMERIC", "Valeur qui périme sous 90 jours"),
            ("qty_expired", "FLOAT64", "Quantité périmée en stock"),
            ("last_sale_date", "DATE", "Dernière vente"),
            ("is_dormant", "BOOL", "Sans vente depuis 60 jours"),
            ("is_out_of_stock", "BOOL", "Rupture à l'officine"),
            ("national_shortage", "BOOL", "Rupture ou tension nationale"),
        ],
    },
    "missing_item": {
        "description": "Manquants : demandes non servies, promis « à rendre » et ventes perdues.",
        "sql": """
            SELECT m.id, m.date, m.product_id, m.patient_id, m.prescriber_id, m.quantity,
                   m.reason, m.outcome, m.state, m.unit_price, m.amount_lost,
                   m.delivered_date, m.delay_days
              FROM pharma_missing_item m
        """,
        "columns": [
            ("id", "INT64", "Identifiant"),
            ("date", "TIMESTAMP", "Date et heure de la demande (UTC)"),
            ("product_id", "INT64", "Article"),
            ("patient_key", "STRING", "Patient (clé pseudonyme)"),
            ("prescriber_id", "INT64", "Prescripteur"),
            ("quantity", "FLOAT64", "Quantité demandée"),
            ("reason", "STRING", "stock (rupture officine), national_shortage…"),
            ("outcome", "STRING", "deferred (promis) ou lost (vente perdue)"),
            ("state", "STRING", "open, delivered, cancelled, closed"),
            ("unit_price", "NUMERIC", "Prix unitaire TTC"),
            ("amount_lost", "NUMERIC", "Chiffre perdu TTC"),
            ("delivered_date", "TIMESTAMP", "Date de délivrance du promis (UTC)"),
            ("delay_days", "NUMERIC", "Délai avant délivrance (jours)"),
        ],
    },
    "health_service": {
        "description": "Missions de santé : vaccinations, TROD, bilans, entretiens.",
        "sql": """
            SELECT s.id, s.date, s.state, t.code AS type_code,
                   COALESCE(to_jsonb(t.name)->>'fr_FR', to_jsonb(t.name)->>'en_US',
                            t.name::text) AS type_name,
                   s.category, s.patient_id, s.pharmacist_id, s.duration_minutes,
                   s.amount_total, s.amount_amo, s.amount_amc, s.amount_patient
              FROM pharma_health_service s
              JOIN pharma_health_service_type t ON t.id = s.type_id
        """,
        "columns": [
            ("id", "INT64", "Identifiant"),
            ("date", "TIMESTAMP", "Date et heure (UTC)"),
            ("state", "STRING", "État : draft, done, cancelled"),
            ("type_code", "STRING", "Code du type de mission"),
            ("type_name", "STRING", "Type de mission"),
            ("category", "STRING", "vaccination, test, review, interview"),
            ("patient_key", "STRING", "Patient (clé pseudonyme)"),
            ("pharmacist_id", "INT64", "Pharmacien"),
            ("duration_minutes", "INT64", "Durée (minutes)"),
            ("amount_total", "NUMERIC", "Montant facturé"),
            ("amount_amo", "NUMERIC", "Part Assurance maladie"),
            ("amount_amc", "NUMERIC", "Part complémentaire"),
            ("amount_patient", "NUMERIC", "Part patient"),
        ],
    },
    "inventory_gap": {
        "description": "Écarts constatés lors des inventaires (démarque inconnue).",
        "sql": """
            SELECT g.id, g.date, g.product_id, g.reason, g.theoretical_qty, g.counted_qty,
                   g.gap_qty, g.unit_cost, g.gap_value
              FROM pharma_inventory_gap g
        """,
        "columns": [
            ("id", "INT64", "Identifiant"),
            ("date", "TIMESTAMP", "Date et heure (UTC)"),
            ("product_id", "INT64", "Article"),
            ("reason", "STRING", "cycle_count (inventaire tournant), full_count…"),
            ("theoretical_qty", "FLOAT64", "Stock théorique"),
            ("counted_qty", "FLOAT64", "Stock compté"),
            ("gap_qty", "FLOAT64", "Écart (compté − théorique)"),
            ("unit_cost", "NUMERIC", "Coût unitaire"),
            ("gap_value", "NUMERIC", "Écart valorisé au coût"),
        ],
    },
    "cash_forecast": {
        "description": "Prévision de trésorerie à 60 jours, calculée par Odoo le jour de l'export.",
        "sql": """
            SELECT f.date, f.inflow_amo, f.inflow_amc, f.inflow_other, f.outflow_suppliers,
                   f.net, f.balance, f.overdue_in, f.overdue_out
              FROM pharma_cash_forecast f
        """,
        "columns": [
            ("date", "DATE", "Jour"),
            ("inflow_amo", "NUMERIC", "Encaissements attendus de l'Assurance maladie"),
            ("inflow_amc", "NUMERIC", "Encaissements attendus des complémentaires"),
            ("inflow_other", "NUMERIC", "Autres encaissements attendus"),
            ("outflow_suppliers", "NUMERIC", "Paiements fournisseurs à échéance"),
            ("net", "NUMERIC", "Flux net du jour"),
            ("balance", "NUMERIC", "Solde prévisionnel en fin de journée"),
            ("overdue_in", "NUMERIC", "Créances en retard (premier jour seulement)"),
            ("overdue_out", "NUMERIC", "Dettes en retard (premier jour seulement)"),
        ],
    },
}


def pseudo_key(secret: bytes, patient_id):
    if patient_id is None:
        return None
    digest = hmac.new(secret, f"patient:{patient_id}".encode(), hashlib.sha256).hexdigest()
    return digest[:20]


def load_secret(repo_root: Path) -> bytes:
    value = os.environ.get("PHARMA_PSEUDO_KEY")
    if value:
        return value.encode()
    path = repo_root / ".pseudo_key"
    if not path.exists():
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
        print(f"Clé de pseudonymisation créée : {path} (à conserver, ne pas partager)")
    return path.read_text().strip().encode()


def to_csv(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value.quantize(Decimal("0.000001")).normalize(), "f")
    if isinstance(value, dict):  # champ traduisible resté en JSON
        return value.get("fr_FR") or value.get("en_US") or ""
    return str(value)


def export_table(cur, name, spec, out_dir, secret):
    cur.execute(spec["sql"])
    names = [d.name for d in cur.description]
    expected = [c[0] for c in spec["columns"]]
    renamed = ["patient_key" if n == "patient_id" else n for n in names]
    if renamed != expected:
        raise SystemExit(f"{name} : colonnes {renamed} différentes de la définition {expected}")
    patient_idx = names.index("patient_id") if "patient_id" in names else None
    count = 0
    with open(out_dir / f"{name}.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(expected)
        for row in cur:
            row = list(row)
            if patient_idx is not None:
                row[patient_idx] = pseudo_key(secret, row[patient_idx])
            writer.writerow([to_csv(v) for v in row])
            count += 1
    schema = [{"name": n, "type": t, "mode": "NULLABLE", "description": d}
              for n, t, d in spec["columns"]]
    (out_dir / f"{name}.schema.json").write_text(json.dumps(schema, ensure_ascii=False, indent=1))
    return count


def write_lookup(cur, path, secret, out_dir):
    """Correspondance clé → patient, pour que le pharmacien retrouve qui rappeler."""
    if out_dir.resolve() in path.resolve().parents:
        raise SystemExit("La correspondance ne doit pas être écrite dans le dossier chargé dans le cloud.")
    path.parent.mkdir(parents=True, exist_ok=True)
    cur.execute("SELECT id, name FROM res_partner WHERE pharma_partner_type = 'patient' ORDER BY id")
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["patient_key", "odoo_id", "nom"])
        for patient_id, name in cur:
            writer.writerow([pseudo_key(secret, patient_id), patient_id, name])
    path.chmod(0o600)
    print(f"Correspondance des patients (usage local) : {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dbname", required=True, help="base Odoo, par exemple pharmacie2")
    parser.add_argument("--host", default=os.environ.get("PGHOST", "localhost"))
    parser.add_argument("--port", default=os.environ.get("PGPORT", "55432"))
    parser.add_argument("--user", default=os.environ.get("PGUSER", "odoo"))
    parser.add_argument("--out", default="export", help="dossier de sortie (défaut : export/)")
    parser.add_argument(
        "--correspondance", metavar="FICHIER",
        help="écrit aussi, pour un usage local seulement, la table clé pseudonyme → patient "
             "(nom, identifiant Odoo) ; à garder sur le poste, jamais dans le cloud")
    args = parser.parse_args()

    import psycopg2

    repo_root = Path(__file__).resolve().parent.parent
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    secret = load_secret(repo_root)
    conn = psycopg2.connect(dbname=args.dbname, host=args.host, port=args.port, user=args.user,
                            password=os.environ.get("PGPASSWORD", "odoo"))
    conn.set_session(readonly=True)
    manifest = {"exported_at": datetime.now().isoformat(timespec="seconds"),
                "database": args.dbname, "tables": {}}
    with conn, conn.cursor() as cur:
        for name, spec in TABLES.items():
            count = export_table(cur, name, spec, out_dir, secret)
            manifest["tables"][name] = {"rows": count, "description": spec["description"]}
            print(f"{name:20} {count:>8} lignes")
        if args.correspondance:
            write_lookup(cur, Path(args.correspondance), secret, out_dir)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
