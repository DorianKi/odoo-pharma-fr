"""Générateur de données fictives : plusieurs mois d'activité d'une officine parisienne.

À exécuter dans le shell Odoo, sur une base où les modules pharma_fr_* sont installés
et la BDPM importée :

    docker compose exec -T odoo odoo shell -d pharmacie --no-http \\
        --db_host=db --db_user=odoo --db_password=odoo < scripts/generate_demo_data.py

Paramètres (variables d'environnement, à passer avec ``docker compose exec -e``) :

    DEMO_MONTHS nombre de mois simulés, du 1er du mois jusqu'à la veille (défaut 3)
    DEMO_DAYS   à la place de DEMO_MONTHS : nombre de jours se terminant la veille
    DEMO_SCALE  coefficient d'activité (défaut 2.0 ; environ 100 passages par jour ouvré)
    DEMO_SEED   graine aléatoire (défaut 42) : même graine, mêmes données
    DEMO_FORCE  1 pour relancer sur une base déjà générée

L'horloge d'Odoo est simulée (freezegun) : mouvements de stock, factures, registres
et ordonnancier portent les dates simulées.

Toutes les personnes (patients, prescripteurs) et les organismes privés sont fictifs.
Les médicaments, laboratoires et prix proviennent de la BDPM. Les coûts d'achat sont
estimés.

Problèmes de gestion volontairement introduits, pour l'analyse :
  * surstock : commandes directes trop généreuses chez le génériqueur, produits dormants ;
  * péremption : lots à date courte sur des produits surstockés, puis destructions ;
  * ruptures : produits en rupture nationale (ANSM) mal livrés, d'où des manquants ;
  * dépannages chez le second grossiste, aux conditions moins favorables ;
  * substitution générique freinée par un prescripteur (« non substituable ») et
    quelques refus de patients ;
  * commandes sous le franco chez le fournisseur de parapharmacie ;
  * réassort calé sur la demande moyenne, sans anticiper la hausse saisonnière
    d'octobre (antibiotiques, antalgiques), d'où des manquants ;
  * retours patients et destructions.
"""

import logging
import math
import os
import random
import re
import time
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta

import pytz
from freezegun import freeze_time

from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger("pharma_fr_demo")

MONTHS = int(os.environ.get("DEMO_MONTHS", 3))
DAYS = int(os.environ["DEMO_DAYS"]) if os.environ.get("DEMO_DAYS") else None
SCALE = float(os.environ.get("DEMO_SCALE", 2.0))
SEED = int(os.environ.get("DEMO_SEED", 42))
FORCE = os.environ.get("DEMO_FORCE") == "1"

# ---------------------------------------------------------------------------
# Référentiels de simulation
# ---------------------------------------------------------------------------

# (motif de recherche sur la substance, poids de demande, profil, nombre de produits)
# Profil : chronic = traitement au long cours renouvelé chaque mois, acute = ponctuel.
MOLECULES = [
    ("paracetamol", 30, "acute", 4), ("ibuprofene", 8, "acute", 3),
    ("amoxicilline", 9, "acute", 3), ("acide clavulanique", 5, "acute", 2),
    ("azithromycine", 3, "acute", 2), ("prednisolone", 4, "acute", 2),
    ("cetirizine", 3, "acute", 2), ("desloratadine", 3, "acute", 2),
    ("phloroglucinol", 4, "acute", 2), ("diosmectite", 3, "acute", 2),
    ("fosfomycine", 2, "acute", 2), ("ketoprofene", 2, "acute", 2),
    ("nefopam", 2, "acute", 1), ("tramadol", 3, "acute", 2),
    ("codeine", 2, "acute", 2), ("hydroxyzine", 2, "acute", 2),
    ("macrogol", 2, "acute", 2), ("metoclopramide", 1, "acute", 1),
    ("levothyroxine", 9, "chronic", 3), ("metformine", 8, "chronic", 3),
    ("atorvastatine", 8, "chronic", 3), ("rosuvastatine", 6, "chronic", 3),
    ("amlodipine", 7, "chronic", 3), ("ramipril", 6, "chronic", 3),
    ("perindopril", 4, "chronic", 2), ("bisoprolol", 6, "chronic", 3),
    ("esomeprazole", 6, "chronic", 3), ("omeprazole", 4, "chronic", 2),
    ("pantoprazole", 3, "chronic", 2), ("furosemide", 3, "chronic", 2),
    ("escitalopram", 4, "chronic", 2), ("sertraline", 3, "chronic", 2),
    ("alprazolam", 3, "chronic", 2), ("zolpidem", 3, "chronic", 2),
    ("apixaban", 4, "chronic", 2), ("rivaroxaban", 3, "chronic", 2),
    ("acetylsalicylique", 4, "chronic", 2), ("clopidogrel", 3, "chronic", 2),
    ("losartan", 3, "chronic", 2), ("valsartan", 3, "chronic", 2),
    ("tamsulosine", 3, "chronic", 2), ("allopurinol", 2, "chronic", 2),
    ("salbutamol", 3, "chronic", 2), ("pregabaline", 2, "chronic", 2),
    ("colecalciferol", 3, "chronic", 2), ("dapagliflozine", 3, "chronic", 1),
    ("empagliflozine", 2, "chronic", 1), ("sitagliptine", 3, "chronic", 2),
    ("ezetimibe", 3, "chronic", 2), ("sacubitril", 2, "chronic", 1),
    ("ticagrelor", 1, "chronic", 1), ("tiotropium", 2, "chronic", 1),
    ("fluticasone", 2, "chronic", 2), ("morphine", 1, "chronic", 1),
    ("oxycodone", 1, "chronic", 1),
]

PARAPHARMACY = [
    # (nom, prix TTC, catégorie, poids de demande)
    ("Crème hydratante visage peaux sèches 50 ml", 14.90, "parapharmacy", 3),
    ("Écran solaire visage SPF50+ 50 ml", 17.50, "parapharmacy", 3),
    ("Lait solaire enfant SPF50+ 200 ml", 19.90, "parapharmacy", 2),
    ("Baume lèvres réparateur 15 ml", 6.90, "parapharmacy", 2),
    ("Shampooing antipelliculaire 200 ml", 11.50, "parapharmacy", 2),
    ("Gel lavant surgras 500 ml", 9.90, "parapharmacy", 3),
    ("Crème mains réparatrice 75 ml", 7.90, "parapharmacy", 2),
    ("Eau micellaire peaux sensibles 400 ml", 12.90, "parapharmacy", 3),
    ("Sérum anti-âge 30 ml", 34.90, "parapharmacy", 1),
    ("Déodorant 48 h sans sels d'aluminium", 8.50, "parapharmacy", 2),
    ("Dentifrice gencives sensibles 75 ml", 5.90, "parapharmacy", 3),
    ("Bain de bouche antiseptique 300 ml", 7.20, "parapharmacy", 1),
    ("Spray nasal eau de mer 100 ml", 6.50, "parapharmacy", 4),
    ("Pastilles gorge miel citron x 24", 6.90, "parapharmacy", 3),
    ("Sirop toux sèche et grasse 150 ml", 9.50, "parapharmacy", 2),
    ("Probiotiques flore intestinale x 30", 19.90, "parapharmacy", 2),
    ("Magnésium B6 x 60", 12.90, "parapharmacy", 3),
    ("Vitamine C 1000 mg x 20", 8.90, "parapharmacy", 2),
    ("Mélatonine 1,9 mg x 60", 13.50, "parapharmacy", 2),
    ("Complément articulations x 90", 24.90, "parapharmacy", 1),
    ("Répulsif moustiques zones tropicales 100 ml", 11.90, "parapharmacy", 1),
    ("Lait infantile 1er âge 800 g", 21.90, "parapharmacy", 2),
    ("Liniment oléo-calcaire 500 ml", 8.90, "parapharmacy", 2),
    ("Crème change bébé 100 g", 7.50, "parapharmacy", 2),
    ("Préservatifs x 12", 9.90, "parapharmacy", 1),
    ("Test de grossesse x 1", 8.90, "parapharmacy", 1),
    ("Pansements assortis x 30", 4.90, "medical_device", 3),
    ("Compresses stériles 7,5 x 7,5 x 50", 6.20, "medical_device", 2),
    ("Thermomètre électronique flexible", 9.90, "medical_device", 1),
    ("Tensiomètre poignet", 39.90, "medical_device", 1),
    ("Bas de contention classe 2 (paire)", 34.90, "medical_device", 1),
    ("Masques chirurgicaux x 50", 7.90, "medical_device", 2),
    ("Bandelettes glycémie x 50", 22.90, "medical_device", 1),
    ("Chevillère ligamentaire", 24.90, "medical_device", 1),
    ("Sérum physiologique unidoses x 40", 4.50, "medical_device", 4),
]

FIRST_NAMES_F = ["Marie", "Camille", "Léa", "Manon", "Chloé", "Inès", "Sarah", "Julie", "Emma",
                 "Louise", "Alice", "Nathalie", "Sophie", "Isabelle", "Catherine", "Sylvie",
                 "Françoise", "Monique", "Christine", "Aïcha", "Fatou", "Mei", "Clara", "Anne",
                 "Jeanne", "Hélène", "Martine", "Nadia", "Yasmine", "Élodie"]
FIRST_NAMES_M = ["Thomas", "Nicolas", "Julien", "Lucas", "Hugo", "Karim", "Mehdi", "Antoine",
                 "Pierre", "Jean", "Michel", "Philippe", "Alain", "Bernard", "Patrick", "Louis",
                 "Gabriel", "Arthur", "Mamadou", "Wei", "Paul", "Olivier", "François", "Yanis",
                 "Raphaël", "Samuel", "Didier", "Laurent", "Rachid", "Théo"]
LAST_NAMES = ["Martin", "Bernard", "Dubois", "Thomas", "Robert", "Richard", "Petit", "Durand",
              "Leroy", "Moreau", "Simon", "Laurent", "Lefebvre", "Michel", "Garcia", "David",
              "Bertrand", "Roux", "Vincent", "Fournier", "Morel", "Girard", "André", "Mercier",
              "Dupont", "Lambert", "Bonnet", "François", "Martinez", "Legrand", "Garnier",
              "Faure", "Rousseau", "Blanc", "Guerin", "Muller", "Henry", "Roussel", "Nicolas",
              "Perrin", "Morin", "Mathieu", "Clement", "Gauthier", "Dumont", "Lopez", "Fontaine",
              "Chevalier", "Robin", "Masson", "Benali", "Haddad", "Nguyen", "Diallo", "Traoré",
              "Kone", "Chen", "Pereira", "Da Silva", "Cohen", "Bouchard", "Renaud", "Marchand"]
STREETS = ["rue de la Roquette", "boulevard Voltaire", "rue Oberkampf", "avenue de la République",
           "rue du Faubourg Saint-Antoine", "rue de Charonne", "avenue Parmentier",
           "rue de la Folie-Méricourt", "rue Saint-Maur", "boulevard Richard-Lenoir",
           "rue Popincourt", "rue Amelot", "rue Jean-Pierre Timbaud", "passage Saint-Ambroise"]
SPECIALTIES = ["Médecine générale"] * 16 + ["Cardiologie", "Pédiatrie", "Psychiatrie",
                                             "Rhumatologie", "Endocrinologie", "Pneumologie"]
MUTUELLES = ["Mutuelle Horizon Santé (fictive)", "Mutuelle des Artisans d'Île-de-France (fictive)",
             "Complémentaire Avenir Plus (fictive)", "Mutuelle Fonction Publique Démo (fictive)",
             "Assurance Santé Entreprise Démo (fictive)"]


# Marge dégressive lissée de l'officine (barème applicable depuis le 1er janvier 2020,
# arrêté du 12 novembre 2018) : taux par tranche de prix fabricant HT. À vérifier.
MDL_TRANCHES = [(1.91, 0.10), (22.90, 0.07), (150.00, 0.055), (1600.00, 0.05)]
# Marge du grossiste-répartiteur : approximation (6,93 % du PFHT, bornée).
WHOLESALER_RATE, WHOLESALER_MIN, WHOLESALER_MAX = 0.0693, 0.30, 32.50


def officine_margin(pfht):
    margin, floor = 0.0, 0.0
    for ceiling, rate in MDL_TRANCHES:
        if pfht > floor:
            margin += (min(pfht, ceiling) - floor) * rate
        floor = ceiling
    return margin


def wholesaler_margin(pfht):
    return min(max(pfht * WHOLESALER_RATE, WHOLESALER_MIN), WHOLESALER_MAX)


def pfht_from_public_price(ppttc, vat=2.1):
    """Prix fabricant HT déduit du prix public TTC (hors honoraires) d'un médicament
    remboursable : PPTTC = (PFHT + marge grossiste + marge officine) × (1 + TVA)."""
    ppht = ppttc / (1 + vat / 100)
    low, high = 0.0, ppht
    for _i in range(60):
        mid = (low + high) / 2
        if mid + wholesaler_margin(mid) + officine_margin(mid) > ppht:
            high = mid
        else:
            low = mid
    return round(low, 4)


def normalize(text):
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def nir_for(sex, birthdate, rng):
    """NIR fictif mais valide (clé de contrôle), né à Paris."""
    body = f"{1 if sex == 'M' else 2}{birthdate:%y%m}75{rng.randint(101, 120):03d}{rng.randint(1, 999):03d}"
    key = 97 - int(body) % 97
    return f"{body}{key:02d}"


class Simulation:

    def __init__(self, env):
        self.env = env
        self.rng = random.Random(SEED)
        self.company = env.company
        self.today = date.today()
        self.end = self.today - timedelta(days=1)
        if DAYS:
            self.start = self.end - timedelta(days=DAYS - 1)
        else:  # mois complets : du 1er du mois, (MONTHS - 1) mois avant le mois courant
            month_index = self.end.year * 12 + self.end.month - 1 - (MONTHS - 1)
            self.start = date(month_index // 12, month_index % 12 + 1, 1)
        self.warehouse = env["stock.warehouse"].search([("company_id", "=", self.company.id)], limit=1)
        self.stock = self.warehouse.lot_stock_id
        self.stats = defaultdict(int)
        self.demand = {}           # product_id -> demande estimée (boîtes par jour)
        self.popularity = {}       # product_id -> poids de prescription (fixe)
        self.sold_today = defaultdict(float)
        self.molecules = {}        # motif -> {weight, profile, princeps, generics, products}
        self.pending = defaultdict(list)   # date -> [picking]
        self.on_order = defaultdict(float)  # product_id -> quantité commandée non reçue
        self.supplier_of = {}      # product_id -> fournisseur habituel
        self.para_products = []
        self.otc_products = []

    # ------------------------------------------------------------------
    # Outils
    # ------------------------------------------------------------------

    def log(self, msg, *args):
        _logger.info(msg, *args)
        print(msg % args if args else msg, flush=True)

    def qty(self, product):
        return product.with_context(warehouse_id=self.warehouse.id).qty_available

    def opening_days(self):
        day = self.start
        while day <= self.end:
            if day.weekday() != 6:  # fermé le dimanche
                yield day
            day += timedelta(days=1)

    def poisson(self, lam):
        if lam <= 0:
            return 0
        if lam > 30:
            return max(0, round(self.rng.gauss(lam, math.sqrt(lam))))
        threshold, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= self.rng.random()
            if p <= threshold:
                return k
            k += 1

    def activity_factor(self, day):
        weekday = [1.25, 1.0, 1.0, 1.05, 1.1, 0.75][day.weekday()]
        season = 0.72 if day.month == 8 else (1.1 if day.month in (9, 10) else 1.0)
        return weekday * season * SCALE

    # ------------------------------------------------------------------
    # Mise en place
    # ------------------------------------------------------------------

    def check(self):
        Module = self.env["ir.module.module"]
        for name in ("pharma_fr_purchase", "pharma_fr_dispensation", "pharma_fr_regulatory",
                     "pharma_fr_services", "pharma_fr_analytics"):
            if Module.search_count([("name", "=", name), ("state", "=", "installed")]) == 0:
                raise UserError(f"Le module {name} doit être installé (Applications).")
        if not self.env["pharma.presentation"].search_count([]):
            raise UserError("Importez d'abord la BDPM (Pharmacie > Configuration > Import BDPM).")
        param = self.env["ir.config_parameter"].sudo()
        if param.get_param("pharma_fr_demo.generated") and not FORCE:
            raise UserError("Les données de démonstration ont déjà été générées "
                            "(relancer avec DEMO_FORCE=1 pour forcer).")
        if self.company.chart_template != "fr":
            self.log("Attention : le plan comptable de la société n'est pas le plan français.")

    def setup_company(self):
        company = self.company
        if company.name in ("My Company", "YourCompany", "Ma société"):
            company.name = "Pharmacie du Centre (démo)"
        company.write({
            "street": company.street or "42 boulevard Voltaire",
            "zip": company.zip or "75011",
            "city": company.city or "Paris",
            "country_id": company.country_id.id or self.env.ref("base.fr").id,
        })
        # Tiers payant facturé par bordereaux journaliers ; parts patients regroupées
        # comme un ticket Z de caisse.
        counter = self.env["res.partner"].create({"name": "Encaissements comptoir", "is_company": True})
        company.write({"pharma_invoicing_mode": "daily", "pharma_counter_partner_id": counter.id})
        fefo = self.env.ref("product_expiry.removal_fefo", raise_if_not_found=False)
        if fefo:
            self.stock.removal_strategy_id = fefo

    def select_assortment(self):
        """Choisit les présentations référencées : pour chaque molécule, le princeps
        et quelques génériques du groupe générique le plus fourni."""
        Spec = self.env["pharma.specialite"]
        specs = Spec.search_read(
            [("is_marketed", "=", True), ("hospital_reserved", "=", False)],
            ["id", "name", "active_substances", "generic_group_id", "generic_type",
             "laboratory_id", "availability_status", "pharmaceutical_form"],
        )
        # Officine de ville : on écarte les formes injectables.
        specs = [s for s in specs if not re.search(
            r"injectable|perfusion", normalize(s["pharmaceutical_form"]))]
        # Chaque spécialité est rattachée à une seule molécule : les associations
        # (amoxicilline + acide clavulanique, paracétamol + codéine) sont testées en premier.
        combos = ("acide clavulanique", "codeine")
        priority = [m[0] for m in MOLECULES if m[0] in combos] + [
            m[0] for m in MOLECULES if m[0] not in combos]
        by_pattern = defaultdict(list)
        for spec in specs:
            substances = normalize(spec["active_substances"])
            name = normalize(spec["name"])
            for pattern in priority:
                if pattern in substances or name.startswith(pattern):
                    by_pattern[pattern].append(spec)
                    break
        Pres = self.env["pharma.presentation"]
        chosen = Pres.browse()
        for pattern, weight, profile, count in MOLECULES:
            candidates = by_pattern.get(pattern)
            if not candidates:
                continue
            groups = defaultdict(list)
            for spec in candidates:
                groups[spec["generic_group_id"] and spec["generic_group_id"][0]].append(spec["id"])
            best_group = max(groups, key=lambda g: (bool(g), len(groups[g])))
            presentations = Pres.search([
                ("specialite_id", "in", groups[best_group]),
                ("is_marketed", "=", True),
                ("price_ttc", ">", 0),
            ], order="price_ttc desc")
            if not presentations:
                continue
            princeps = presentations.filtered(lambda p: p.generic_type == "princeps")[:1]
            generics = presentations.filtered(lambda p: p.generic_type and p.generic_type != "princeps")
            picked = princeps
            seen_labs = set()
            for pres in generics:
                if len(picked) >= count:
                    break
                if pres.laboratory_id.id not in seen_labs:
                    picked |= pres
                    seen_labs.add(pres.laboratory_id.id)
            if len(picked) < count:
                picked |= (presentations - picked)[: count - len(picked)]
            self.molecules[pattern] = {
                "weight": weight, "profile": profile, "presentations": picked,
            }
            chosen |= picked
        # Médicaments non remboursables (conseil) : prix libre fixé par l'officine.
        otc = Pres.search([
            ("is_marketed", "=", True), ("reimbursement_rate", "=", "0"),
            ("prescription_list", "=", "none"), ("specialite_id.hospital_reserved", "=", False),
        ])
        otc = otc.browse(self.rng.sample(otc.ids, min(40, len(otc))))
        if not chosen:
            # Base de test réduite : on prend ce qui existe.
            chosen = Pres.search([("is_marketed", "=", True), ("price_ttc", ">", 0)], limit=50)
            for pres in chosen:
                self.molecules[pres.cip13] = {
                    "weight": 3, "profile": self.rng.choice(["acute", "chronic"]),
                    "presentations": pres,
                }
        products = (chosen | otc)._create_products()
        self.stats["articles_medicaments"] = len(products)
        for pres in otc:
            price = round(self.rng.uniform(3.5, 14.0), 2)
            tmpl = pres.product_tmpl_id
            tmpl.write(tmpl._pharma_prepare_tax_vals("10", price))
            self.otc_products.append((tmpl.product_variant_id, self.rng.uniform(0.5, 2.0)))
        self.log("Assortiment : %s médicaments (%s molécules) et %s conseils",
                 len(chosen), len(self.molecules), len(otc))

    def create_parapharmacy(self):
        Product = self.env["product.template"]
        for name, price, category, weight in PARAPHARMACY:
            tmpl = Product.create(dict({
                "name": name,
                "type": "consu",
                "is_storable": True,
                "pharma_category": category,
                "barcode": f"37{self.rng.randint(10**10, 10**11 - 1)}",
                "sale_ok": True,
                "purchase_ok": True,
            }, **Product._pharma_prepare_tax_vals("20", price)))
            self.para_products.append((tmpl.product_variant_id, weight))
        self.log("Parapharmacie : %s articles", len(self.para_products))

    def create_partners(self):
        Partner = self.env["res.partner"]
        rng = self.rng
        self.wholesaler = Partner.create({
            "name": "Répartiteur Paris Est (fictif)", "is_company": True,
            "pharma_partner_type": "wholesaler", "pharma_is_main_wholesaler": True,
            "pharma_deliveries_per_day": 2, "city": "Paris",
        })
        self.backup_wholesaler = Partner.create({
            "name": "Répartiteur Île-de-France Sud (fictif)", "is_company": True,
            "pharma_partner_type": "wholesaler", "pharma_deliveries_per_day": 1,
            "city": "Ivry-sur-Seine",
        })
        self.para_supplier = Partner.create({
            "name": "Distrib'Para (fictif)", "is_company": True,
            "pharma_partner_type": "laboratory", "pharma_franco_amount": 400.0,
        })
        self.cpam = Partner.create({
            "name": "CPAM de Paris", "is_company": True, "pharma_partner_type": "insurer",
            "pharma_insurer_type": "amo", "pharma_insurer_code": "751", "city": "Paris",
            "pharma_payment_delay_days": 5,
        })
        self.mutuelles = Partner.create([{
            "name": name, "is_company": True, "pharma_partner_type": "insurer",
            "pharma_insurer_type": "amc", "pharma_payment_delay_days": 12 + 4 * i,
        } for i, name in enumerate(MUTUELLES)])
        self.walk_in = Partner.create({
            "name": "Client de passage", "pharma_partner_type": "patient",
            "pharma_tiers_payant": False, "pharma_amc_coverage": "none",
        })
        prescribers = []
        for i in range(24):
            sex = rng.choice("MF")
            first = rng.choice(FIRST_NAMES_M if sex == "M" else FIRST_NAMES_F)
            prescribers.append({
                "name": f"Dr {first} {rng.choice(LAST_NAMES)}",
                "pharma_partner_type": "prescriber",
                "pharma_rpps": f"10{rng.randint(10**8, 10**9 - 1)}",
                "pharma_specialty": SPECIALTIES[i % len(SPECIALTIES)],
                "city": "Paris",
            })
        self.prescribers = Partner.create(prescribers)
        # Ce prescripteur porte souvent la mention « non substituable ».
        self.ns_prescriber = self.prescribers[3]
        self.prescriber_weights = [rng.uniform(0.3, 3) for _p in self.prescribers]
        patients = []
        for _i in range(int(800 * max(SCALE, 0.3))):
            sex = rng.choice("MF")
            age = int(min(98, max(0, rng.gauss(50, 22))))
            birth = self.start - timedelta(days=age * 365 + rng.randint(0, 364))
            first = rng.choice(FIRST_NAMES_M if sex == "M" else FIRST_NAMES_F)
            has_amc = rng.random() < 0.88
            exemption = "none"
            if rng.random() < 0.07:
                exemption = "c2s"
            elif age > 55 and rng.random() < 0.35:
                exemption = "ald"
            arrondissement = rng.choice([11, 11, 11, 12, 20, 3, 10])
            patients.append({
                "name": f"{first} {rng.choice(LAST_NAMES)}",
                "pharma_partner_type": "patient",
                "pharma_birthdate": birth,
                "pharma_nir": nir_for(sex, birth, rng),
                "pharma_amo_id": self.cpam.id,
                "pharma_amc_id": rng.choice(self.mutuelles).id if has_amc else False,
                "pharma_amc_coverage": rng.choice(["tm"] * 4 + ["tm_except_15"]) if has_amc else "none",
                "pharma_exemption": exemption,
                "pharma_tiers_payant": rng.random() < 0.96,
                "street": f"{rng.randint(1, 140)} {rng.choice(STREETS)}",
                "zip": f"750{arrondissement:02d}",
                "city": "Paris",
            })
        self.patients = Partner.create(patients)
        self.log("Partenaires : %s patients, %s prescripteurs", len(self.patients), len(self.prescribers))

    def create_team(self):
        """A. L'équipe : titulaire, adjoint et préparateurs, avec des profils de vente
        différents (taux de conseil associé aux ordonnances)."""
        Users = self.env["res.users"].with_context(no_reset_password=True)
        group = self.env.ref("pharma_fr_base.group_pharma_user")
        team = [
            ("Claire Morel (titulaire)", "titulaire", True, 0.30, 1.0),
            ("Youssef Benali (adjoint)", "adjoint", True, 0.25, 1.1),
            ("Sophie Lambert (préparatrice)", "preparatrice1", False, 0.28, 1.3),
            ("Kevin Nguyen (préparateur)", "preparateur2", False, 0.08, 1.2),
            ("Inès Diallo (préparatrice)", "preparatrice3", False, 0.18, 0.9),
        ]
        self.sellers, self.seller_weights, self.conseil_rate = [], [], {}
        self.pharmacists = []
        for name, login, pharmacist, conseil, weight in team:
            user = Users.search([("login", "=", f"demo.{login}")], limit=1) or Users.create({
                "name": name, "login": f"demo.{login}", "group_ids": [Command.link(group.id)],
            })
            self.sellers.append(user)
            self.seller_weights.append(weight)
            self.conseil_rate[user.id] = conseil
            if pharmacist:
                self.pharmacists.append(user)
        self.log("Équipe : %s personnes", len(self.sellers))

    def pick_seller(self, pharmacist=False):
        if pharmacist:
            return self.rng.choice(self.pharmacists)
        return self.rng.choices(self.sellers, self.seller_weights)[0]

    def setup_purchasing(self):
        """Tarifs fournisseurs, conditions commerciales et demande par article."""
        rng = self.rng
        Supplierinfo = self.env["product.supplierinfo"]
        generic_labs = defaultdict(int)
        total_weight = sum(m["weight"] for m in self.molecules.values()) or 1
        base_boxes_per_day = 95 * SCALE  # boîtes de médicaments remboursables par jour
        for mol in self.molecules.values():
            presentations = mol["presentations"]
            boxes = base_boxes_per_day * mol["weight"] / total_weight
            shares = [0.3 if p.generic_type == "princeps" else 1.0 for p in presentations]
            for pres, share in zip(presentations, shares, strict=True):
                product = pres.product_tmpl_id.product_variant_id
                self.demand[product.id] = boxes * share / sum(shares)
                if pres.generic_type and pres.generic_type != "princeps":
                    generic_labs[pres.laboratory_id.id] += 1
        self.generic_lab = self.env["res.partner"].browse(
            max(generic_labs, key=generic_labs.get) if generic_labs else []
        )
        if self.generic_lab:
            self.generic_lab.pharma_franco_amount = 500.0
        for product, weight in self.otc_products:
            self.demand[product.id] = weight * 0.8 * SCALE
        for product, weight in self.para_products:
            self.demand[product.id] = weight * 0.9 * SCALE
        # Produits dormants : demande quasi nulle.
        drug_ids = [pid for pid in self.demand if pid not in {p.id for p, _w in self.para_products}]
        self.dormant = set(rng.sample(drug_ids, max(1, len(drug_ids) // 12)))
        for pid in self.dormant:
            self.demand[pid] = 0.02

        self.generics_by_group = defaultdict(list)
        for product in self.env["product.product"].browse(list(self.demand)):
            tmpl = product.product_tmpl_id
            if tmpl.pharma_generic_group_id and tmpl.pharma_generic_type not in (False, "princeps"):
                self.generics_by_group[tmpl.pharma_generic_group_id.id].append(product.id)

        vals = []
        for product in self.env["product.product"].browse(list(self.demand)):
            tmpl = product.product_tmpl_id
            vat = float(tmpl.pharma_vat_rate or 20)
            price_ttc = tmpl.pharma_public_price or tmpl.list_price
            price_ht = price_ttc / (1 + vat / 100)
            pfht = None
            if tmpl.pharma_category == "drug_reimbursed" and tmpl.pharma_public_price:
                # Prix réglementé : achat au grossiste = PFHT + marge du grossiste.
                pfht = pfht_from_public_price(tmpl.pharma_public_price, vat)
                cost = round(pfht + wholesaler_margin(pfht), 2)
            else:
                # Marge commerciale libre : environ 30 % (conseil) à 32-35 % (parapharmacie).
                factor = 0.70 if tmpl.pharma_category == "drug_otc" else 0.68
                cost = round(price_ht * factor * rng.uniform(0.95, 1.05), 2)
            is_para = tmpl.pharma_category in ("parapharmacy", "medical_device")
            main = self.para_supplier if is_para else self.wholesaler
            vals.append({"partner_id": main.id, "product_tmpl_id": tmpl.id, "price": cost,
                         "delay": 2 if is_para else 0, "sequence": 1})
            if not is_para:
                vals.append({"partner_id": self.backup_wholesaler.id, "product_tmpl_id": tmpl.id,
                             "price": round(cost * 1.02, 2), "delay": 0, "sequence": 5})
            direct = (
                self.generic_lab
                and tmpl.pharma_laboratory_id == self.generic_lab
                and tmpl.pharma_generic_type not in (False, "princeps")
            )
            if direct:
                # En direct, le laboratoire facture au PFHT (pas de marge grossiste).
                vals.append({"partner_id": self.generic_lab.id, "product_tmpl_id": tmpl.id,
                             "price": round(pfht or cost, 2), "delay": 3, "sequence": 2})
            self.supplier_of[product.id] = self.generic_lab if direct else main
            discount = 0.20 if tmpl.pharma_generic_type not in (False, "princeps") else (
                0.08 if is_para else 0.02)
            tmpl.standard_price = round(cost * (1 - discount), 4)
        Supplierinfo.create(vals)

        Agreement = self.env["pharma.purchase.agreement"]
        start = self.start - timedelta(days=60)
        Agreement.create([
            {"name": "Conditions annuelles", "partner_id": self.wholesaler.id, "date_start": start,
             "line_ids": [Command.create({"scope": "all", "discount": 2.5}),
                          Command.create({"scope": "generic", "discount": 22.0, "deferred_rebate": 5.0}),
                          Command.create({"scope": "drug_otc", "discount": 6.0})]},
            {"name": "Conditions de dépannage", "partner_id": self.backup_wholesaler.id,
             "date_start": start,
             "line_ids": [Command.create({"scope": "all", "discount": 0.5}),
                          Command.create({"scope": "generic", "discount": 10.0})]},
            {"name": "Accord parapharmacie", "partner_id": self.para_supplier.id, "date_start": start,
             "line_ids": [Command.create({"scope": "all", "discount": 8.0}),
                          Command.create({"scope": "all", "discount": 12.0, "min_qty": 24})]},
        ])
        if self.generic_lab:
            Agreement.create({
                "name": "Accord génériques (commande directe)", "partner_id": self.generic_lab.id,
                "date_start": start,
                "line_ids": [Command.create({"scope": "generic", "discount": 36.0,
                                             "deferred_rebate": 3.0, "min_qty": 10}),
                             Command.create({"scope": "generic", "discount": 30.0})],
            })
        self.log("Achats : génériqueur principal = %s", self.generic_lab.name or "aucun")

    def calibrate_demand(self):
        """Ajuste la demande estimée (boîtes par jour) au volume réellement simulé :
        renouvellements des chroniques, ordonnances ponctuelles et comptoir."""
        acute_per_day = 24 * SCALE
        chronic_boxes = len(self.plans) * 2.6 * 1.75 / 30.0
        acute_boxes = acute_per_day * 2.0 * 1.33
        for profile, total in (("chronic", chronic_boxes), ("acute", acute_boxes)):
            mols = {m: v for m, v in self.molecules.items() if v["profile"] == profile}
            weight_sum = sum(v["weight"] for v in mols.values()) or 1
            for mol in mols.values():
                products = [p.product_tmpl_id.product_variant_id for p in mol["presentations"]]
                shares = [self.demand.get(p.id, 0) for p in products]
                share_sum = sum(shares) or 1
                for product, share in zip(products, shares, strict=True):
                    if product.id not in self.dormant:
                        self.demand[product.id] = total * mol["weight"] / weight_sum * share / share_sum
        counter_items = 20 * SCALE * 1.9
        catalog = self.para_products + self.otc_products
        weight_sum = sum(w for _p, w in catalog) or 1
        for product, weight in catalog:
            if product.id not in self.dormant:
                self.demand[product.id] = counter_items * weight / weight_sum
        self.popularity = dict(self.demand)
        self.log("Demande estimée : %.0f boîtes et articles par jour", sum(self.demand.values()))

    def learn_demand(self):
        """Le soir, l'officine met à jour sa demande estimée (lissage exponentiel des
        demandes du jour, servies ou non)."""
        for pid in self.demand:
            if pid in self.dormant:
                continue
            self.demand[pid] = 0.9 * self.demand[pid] + 0.1 * max(self.sold_today.get(pid, 0), 0)

    def lot_expiry(self, short=False):
        months = self.rng.randint(2, 5) if short else self.rng.randint(10, 36)
        return fields.Datetime.now() + timedelta(days=30 * months + self.rng.randint(0, 20))

    def initial_stock(self):
        """Inventaire d'ouverture, avec du surstock et des lots à date courte."""
        Quant = self.env["stock.quant"].with_context(inventory_mode=True)
        Lot = self.env["stock.lot"]
        products = self.env["product.product"].browse(list(self.demand))
        self.overstocked = set(self.rng.sample(products.ids, max(1, len(products) // 9)))
        quants = Quant.browse()
        for product in products:
            daily = self.demand[product.id]
            if product.id in self.dormant:
                qty = self.rng.randint(8, 25)
            elif product.id in self.overstocked:
                qty = math.ceil(daily * self.rng.uniform(70, 150)) + 5
            else:
                qty = math.ceil(daily * self.rng.uniform(12, 25)) + 2
            short = product.id in self.overstocked or product.id in self.dormant
            vals = {"product_id": product.id, "location_id": self.stock.id, "inventory_quantity": qty}
            if product.tracking == "lot":
                vals["lot_id"] = Lot.create({
                    "product_id": product.id, "name": f"INV{self.rng.randint(10000, 99999)}",
                    "expiration_date": self.lot_expiry(short=short),
                }).id
            quants |= Quant.create(vals)
        quants.with_context(pharma_skip_gap=True).action_apply_inventory()
        self.log("Stock d'ouverture : %s articles", len(products))

    # ------------------------------------------------------------------
    # Achats et réceptions
    # ------------------------------------------------------------------

    def place_order(self, partner, quantities, due, origin=""):
        lines = [Command.create({"product_id": pid, "product_qty": qty})
                 for pid, qty in quantities.items() if qty > 0]
        if not lines:
            return None
        order = self.env["purchase.order"].create({
            "partner_id": partner.id, "order_line": lines, "origin": origin,
            "date_order": fields.Datetime.now(),
        })
        order.button_confirm()
        for pid, qty in quantities.items():
            self.on_order[pid] += qty
        self.pending[due].extend(order.picking_ids)
        self.stats["commandes"] += 1
        return order

    def receive(self, picking, fill_rates=None):
        if picking.state in ("done", "cancel"):
            return
        commands_by_move = {}
        for move in picking.move_ids:
            product = move.product_id
            rate = (fill_rates or {}).get(product.id, 1.0)
            qty = math.floor(move.product_uom_qty * rate)
            self.on_order[product.id] = max(0.0, self.on_order[product.id] - move.product_uom_qty)
            if qty <= 0:
                commands_by_move[move] = [Command.clear()]
                continue
            line = {"product_id": product.id, "quantity": qty,
                    "location_id": move.location_id.id, "location_dest_id": move.location_dest_id.id}
            if product.tracking == "lot":
                short = product.id in self.overstocked and self.rng.random() < 0.5
                line.update({"lot_name": f"L{self.rng.randint(100000, 999999)}",
                             "expiration_date": self.lot_expiry(short=short or self.rng.random() < 0.04)})
            commands_by_move[move] = [Command.clear(), Command.create(line)]
        for move, commands in commands_by_move.items():
            move.move_line_ids = commands
        received = picking.move_ids.filtered(lambda m: m.move_line_ids)
        if not received:
            picking.action_cancel()
            return
        received.picked = True
        picking.with_context(skip_expired=True, skip_sms=True,
                             picking_ids_not_to_backorder=picking.ids).button_validate()
        self.stats["receptions"] += 1
        self.bill(picking.purchase_id)

    def bill(self, order):
        """Facture fournisseur à réception (quantités reçues)."""
        if not order:
            return
        try:
            with self.env.cr.savepoint():
                order.action_create_invoice()
                bills = order.invoice_ids.filtered(lambda m: m.state == "draft")
                today = fields.Date.today()
                partner = order.partner_id
                if partner.pharma_partner_type == "wholesaler":   # le 10 du mois suivant
                    due = (today.replace(day=1) + timedelta(days=32)).replace(day=10)
                elif partner == self.para_supplier:
                    due = today + timedelta(days=30)
                else:
                    due = today + timedelta(days=60)
                bills.write({"invoice_date": today, "invoice_date_due": due,
                             "ref": f"Facture {partner.name} {order.name}"})
                bills.action_post()
                self.stats["factures_fournisseurs"] += len(bills)
        except UserError as exc:
            _logger.debug("Pas de facture pour %s : %s", order.name, exc)

    def daily_orders(self, day):
        """Commande du matin : réassort chez le grossiste ; commande directe mensuelle
        (trop généreuse) chez le génériqueur ; parapharmacie le lundi et le jeudi."""
        to_wholesaler, to_lab, to_para = {}, {}, {}
        first_monday = day.weekday() == 0 and day.day <= 7
        for pid, daily in self.demand.items():
            supplier = self.supplier_of.get(pid)
            available = self.stock_level[pid] + self.on_order[pid]
            if supplier == self.generic_lab and self.generic_lab:
                if first_monday:
                    target = daily * self.rng.uniform(40, 55)   # trop de couverture
                    if available < target:
                        to_lab[pid] = math.ceil(max(target - available, 10))
                elif available < daily * 2:
                    to_wholesaler[pid] = math.ceil(daily * 6) or 1
                continue
            if supplier == self.para_supplier:
                if day.weekday() in (0, 3) and available < daily * 6:
                    to_para[pid] = math.ceil(daily * self.rng.uniform(8, 14)) or 1
                continue
            if available < daily * 4 + 1:
                to_wholesaler[pid] = max(1, math.ceil(daily * self.rng.uniform(9, 12) - available))
        today = day
        if to_wholesaler:
            self.place_order(self.wholesaler, to_wholesaler, today, "Réassort quotidien")
        if to_lab:
            self.place_order(self.generic_lab, to_lab, self.add_opening_days(day, 3),
                             "Commande directe mensuelle")
        if to_para:
            self.place_order(self.para_supplier, to_para, self.add_opening_days(day, 2),
                             "Commande parapharmacie")

    def add_opening_days(self, day, count):
        while count:
            day += timedelta(days=1)
            if day.weekday() != 6:
                count -= 1
        return day

    def receive_due(self, day):
        for picking in self.pending.pop(day, []):
            fill = {}
            for move in picking.move_ids:
                status = move.product_id.pharma_availability_status
                if status == "shortage":
                    fill[move.product_id.id] = self.rng.choice([0, 0, 0.3])
                elif status == "tension":
                    fill[move.product_id.id] = self.rng.choice([0.5, 1, 1])
            self.receive(picking, fill)

    # ------------------------------------------------------------------
    # Ventes
    # ------------------------------------------------------------------

    def refresh_stock_levels(self):
        data = self.env["stock.quant"]._read_group(
            [("location_id", "=", self.stock.id), ("product_id", "in", list(self.demand))],
            ["product_id"], ["quantity:sum"],
        )
        self.stock_level = defaultdict(float, {p.id: q for p, q in data})

    def pick_presentation(self, molecule):
        presentations = self.molecules[molecule]["presentations"]
        products = [p.product_tmpl_id.product_variant_id for p in presentations]
        weights = [self.popularity.get(p.id, 0.1) for p in products]
        return self.rng.choices(products, weights=weights)[0]

    def substitute(self, product, prescriber, patient):
        """Choisit le produit délivré pour un produit prescrit (substitution générique)."""
        tmpl = product.product_tmpl_id
        flags = {"prescribed_product_id": product.id}
        if tmpl.pharma_generic_type != "princeps" or not tmpl.pharma_generic_group_id:
            return product, {}
        generics = [p for p in self.generics_by_group.get(tmpl.pharma_generic_group_id.id, [])
                    if p != product.id]
        if not generics:
            return product, {}
        if prescriber == self.ns_prescriber and self.rng.random() < 0.45:
            return product, dict(flags, non_substitutable=True)
        if self.rng.random() < 0.07:
            return product, dict(flags, substitution_refused=True)
        if self.rng.random() < 0.88:
            choice = max(generics, key=lambda p: (self.stock_level[p], self.demand[p]))
            return self.env["product.product"].browse(choice), flags
        return product, {}

    def missing(self, product, qty, patient, reason, outcome, prescriber=None):
        tmpl = product.product_tmpl_id
        self.env["pharma.missing.item"].create({
            "product_id": product.id, "quantity": qty, "reason": reason, "outcome": outcome,
            "patient_id": patient.id,
            "prescriber_id": prescriber.id if prescriber else False,
            "unit_price": tmpl.pharma_public_price or tmpl.list_price,
        })
        self.stats["manquants"] += 1

    def serve_lines(self, wanted, patient, prescriber=None):
        """Vérifie le stock ; enregistre les manquants et déclenche les dépannages."""
        lines = []
        for product, qty, extra in wanted:
            if self.stock_level[product.id] >= qty:
                self.stock_level[product.id] -= qty
                self.sold_today[product.id] += qty
                lines.append((product, qty, extra))
                continue
            # La demande non servie compte dans l'estimation de la demande : sinon une
            # rupture ferait chuter la demande estimée et le produit ne serait plus commandé.
            self.sold_today[product.id] += qty
            status = product.pharma_availability_status
            reason = "national_shortage" if status in ("shortage", "tension") else "stock"
            outcome = "lost" if reason == "national_shortage" or self.rng.random() < 0.35 else "deferred"
            self.missing(product, qty, patient, reason, outcome, prescriber)
            if reason == "stock" and product.id not in self.emergency_today:
                self.emergency_today.add(product.id)
                self.emergency[product.id] = math.ceil(self.demand[product.id] * 4) + qty
        return lines

    def visit(self, patient, prescriber, wanted, rx_type="standard", renewal=0, rx_date=None,
              seller=None):
        """Passage au comptoir : vérification du stock, vente additionnelle de conseil
        selon le vendeur, puis délivrance."""
        seller = seller or self.pick_seller(pharmacist=rx_type == "secure")
        if prescriber and self.rng.random() < self.conseil_rate[seller.id]:
            catalog = self.para_products + self.otc_products
            if catalog:
                product = self.rng.choices([p for p, _w in catalog], [w for _p, w in catalog])[0]
                wanted = list(wanted) + [(product, 1, {})]
        lines = self.serve_lines(wanted, patient, prescriber)
        return self.dispense(patient, prescriber, lines, rx_type, renewal, rx_date, seller)

    def dispense(self, patient, prescriber, lines, rx_type="standard", renewal=0, rx_date=None,
                 seller=None):
        if not lines:
            return None
        Prescription = self.env["pharma.prescription"]
        try:
            with self.env.cr.savepoint():
                rx = Prescription.create({
                    "patient_id": patient.id,
                    "prescriber_id": prescriber.id if prescriber else False,
                    "prescription_type": rx_type,
                    "prescription_date": rx_date or fields.Date.today(),
                    "renewal_index": renewal,
                    "dispensing_date": fields.Datetime.now(),
                    "seller_id": (seller or self.sellers[0]).id,
                    "line_ids": [Command.create(dict({"product_id": p.id, "quantity": q}, **extra))
                                 for p, q, extra in lines],
                })
                rx.action_dispense()
                if prescriber:
                    self.dispensed.append(rx.id)
                self.stats["ordonnances" if prescriber else "ventes_comptoir"] += 1
                return rx
        except (UserError, ValidationError) as exc:
            self.stats["delivrances_refusees"] += 1
            for product, qty, _extra in lines:
                self.stock_level[product.id] += qty
                self.sold_today[product.id] -= qty
                self.missing(product, qty, patient, "stock", "deferred", prescriber)
            _logger.debug("Délivrance impossible : %s", exc)
        return None

    def build_chronic_plans(self):
        chronic = [m for m, v in self.molecules.items() if v["profile"] == "chronic"]
        self.plans = []
        if not chronic:
            return
        candidates = [p for p in self.patients if p.pharma_age >= 35]
        for patient in self.rng.sample(candidates, int(len(candidates) * 0.45)):
            count = min(len(chronic), self.rng.choice([1, 2, 2, 3, 3, 4]))
            mols = self.rng.sample(chronic, count)
            narcotic = [m for m in mols if m in ("morphine", "oxycodone")]
            if narcotic and self.rng.random() < 0.8:
                mols = [m for m in mols if m not in narcotic] or [self.rng.choice(chronic)]
            self.plans.append({
                "patient": patient,
                "prescriber": self.rng.choices(self.prescribers, self.prescriber_weights)[0],
                "molecules": mols,
                "products": {m: self.pick_presentation(m) for m in mols},
                "next": self.start + timedelta(days=self.rng.randint(0, 27)),
                "renewal": self.rng.randint(0, 5),
            })
            plan = self.plans[-1]
            plan["rx_date"] = plan["next"] - timedelta(days=30 * plan["renewal"])
            # F. Une partie des patients chroniques part chez un confrère en cours de période.
            if self.rng.random() < 0.07:
                span = max(21, (self.end - self.start).days)
                plan["leaves"] = self.start + timedelta(days=self.rng.randint(20, span))
        self.log("Patients chroniques : %s", len(self.plans))

    def chronic_dispensing(self, day):
        visits = []
        for plan in self.plans:
            if plan["next"] > day or (plan.get("leaves") and plan["leaves"] <= day):
                continue
            patient, prescriber = plan["patient"], plan["prescriber"]
            if plan["renewal"] >= 5:
                plan.update(renewal=0, rx_date=day)
            wanted = []
            for mol in plan["molecules"]:
                product, extra = self.substitute(plan["products"][mol], prescriber, patient)
                if patient.pharma_exemption == "ald":
                    extra = dict(extra, ald_related=True)
                wanted.append((product, self.rng.choice([1, 1, 2, 3]), extra))
            narcotic = any(p.pharma_is_narcotic for p, _q, _e in wanted)
            ald = patient.pharma_exemption == "ald"
            rx_type = "secure" if narcotic else ("bizone" if ald else "standard")
            visits.append(lambda p=patient, d=prescriber, w=wanted, t=rx_type, r=plan["renewal"],
                          x=plan["rx_date"]: self.visit(p, d, w, t, r, x))
            plan["renewal"] += 1
            plan["next"] = day + timedelta(days=self.rng.randint(27, 34))
        return visits

    def acute_dispensing(self, day, count):
        acute = [m for m, v in self.molecules.items() if v["profile"] == "acute"]
        if not acute:
            return []
        visits = []
        weights = [self.molecules[m]["weight"] * (1.3 if day.month >= 10 and m in (
            "amoxicilline", "acide clavulanique", "azithromycine", "paracetamol") else 1)
            for m in acute]
        for _i in range(count):
            patient = self.rng.choice(self.patients)
            prescriber = self.rng.choices(self.prescribers, self.prescriber_weights)[0]
            mols = set(self.rng.choices(acute, weights, k=self.rng.choice([1, 2, 2, 3])))
            wanted = []
            for mol in mols:
                product, extra = self.substitute(self.pick_presentation(mol), prescriber, patient)
                wanted.append((product, self.rng.choice([1, 1, 2]), extra))
            narcotic = any(p.pharma_is_narcotic for p, _q, _e in wanted)
            visits.append(lambda p=patient, d=prescriber, w=wanted,
                          t="secure" if narcotic else "standard": self.visit(p, d, w, t))
        return visits

    def counter_sales(self, count):
        catalog = self.para_products + self.otc_products
        if not catalog:
            return []
        products, weights = zip(*catalog, strict=True)
        visits = []
        for _i in range(count):
            patient = self.walk_in if self.rng.random() < 0.7 else self.rng.choice(self.patients)
            items = set(self.rng.choices(products, weights, k=self.rng.choice([1, 1, 2, 2, 3])))
            wanted = [(p, 1, {}) for p in items]
            visits.append(lambda p=patient, w=wanted: self.visit(p, False, w))
        return visits

    # ------------------------------------------------------------------
    # Opérations quotidiennes
    # ------------------------------------------------------------------

    def destroy_expired(self):
        quants = self.env["stock.quant"].search([
            ("location_id", "=", self.stock.id), ("expiration_date", "<", fields.Datetime.now()),
            ("quantity", ">", 0),
        ])
        if not quants:
            return
        wizard = self.env["pharma.expiry.scrap.wizard"].create({})
        wizard.quant_ids = quants
        wizard.action_scrap()
        self.stats["lots_detruits"] += len(quants)

    def deliver_promises(self, day):
        """G. Après la livraison : délivrance des produits promis (« à rendre ») ; au-delà
        de 5 jours, le patient est allé ailleurs."""
        promises = self.env["pharma.missing.item"].search([
            ("company_id", "=", self.company.id), ("state", "=", "open"),
        ])
        self.refresh_stock_levels()
        for item in promises:
            if (fields.Datetime.now() - item.date).days > 5:
                item.action_cancel()
                self.stats["promis_abandonnes"] += 1
                continue
            product = item.product_id
            if self.stock_level[product.id] < item.quantity or not item.patient_id:
                continue
            self.stock_level[product.id] -= item.quantity
            rx = self.dispense(item.patient_id, item.prescriber_id, [(product, int(item.quantity), {})],
                               "secure" if product.pharma_is_narcotic else "standard",
                               renewal=1 if item.prescriber_id else 0,
                               rx_date=fields.Date.to_date(item.date))
            if rx:
                item.action_mark_delivered(rx)
                self.stats["promis_rendus"] += 1

    def health_services(self, day):
        """C. Missions de santé : TROD angine (plus fréquents à l'automne), campagne de
        vaccination antigrippale à partir de la mi-octobre, entretiens et bilans."""
        Types = self.env["pharma.health.service.type"]
        plan = [
            ("pharma_fr_services.type_trod_angine", 1.5 if day.month >= 9 else 0.5),
            ("pharma_fr_services.type_flu_vaccination",
             10 if (day.month, day.day) >= (10, 14) else 0),
            ("pharma_fr_services.type_other_vaccination", 0.4),
            ("pharma_fr_services.type_bpm", 0.15),
            ("pharma_fr_services.type_aod_interview", 0.35),
            ("pharma_fr_services.type_pregnancy_interview", 0.1),
        ]
        events = []
        seniors = [p for p in self.patients if p.pharma_age >= 65]
        for xmlid, rate in plan:
            service_type = self.env.ref(xmlid, raise_if_not_found=False) or Types.browse()
            for _i in range(self.poisson(rate * self.activity_factor(day) * SCALE / 2)):
                pool = seniors if xmlid.endswith(("bpm", "flu_vaccination")) and seniors else self.patients
                patient = self.rng.choice(pool)
                events.append(lambda t=service_type, p=patient: self.perform_service(t, p))
        return events

    def perform_service(self, service_type, patient):
        if not service_type:
            return
        try:
            with self.env.cr.savepoint():
                service = self.env["pharma.health.service"].create({
                    "type_id": service_type.id, "patient_id": patient.id,
                    "pharmacist_id": self.rng.choice(self.pharmacists).id,
                    "date": fields.Datetime.now(),
                })
                service.action_done()
                self.stats["missions"] += 1
        except (UserError, ValidationError) as exc:
            _logger.warning("Mission impossible : %s", exc)

    def cycle_count(self):
        """E. Inventaire tournant du lundi : une vingtaine d'articles, surtout en
        parapharmacie (en libre accès), où apparaît la démarque inconnue."""
        para_ids = [p.id for p, _w in self.para_products]
        others = [pid for pid in self.demand if pid not in para_ids]
        sample = self.rng.sample(para_ids, min(12, len(para_ids))) + self.rng.sample(
            others, min(8, len(others)))
        Quant = self.env["stock.quant"].with_context(inventory_mode=True)
        counted = Quant.browse()
        for pid in sample:
            quant = Quant.search([("product_id", "=", pid), ("location_id", "=", self.stock.id),
                                  ("quantity", ">", 0)], order="quantity desc", limit=1)
            if not quant:
                continue
            if pid in para_ids:
                gap = -self.rng.choice([1, 1, 2, 3]) if self.rng.random() < 0.30 else 0
            else:
                gap = self.rng.choice([-1, 1]) if self.rng.random() < 0.06 else 0
            quant.inventory_quantity = max(0.0, quant.quantity + gap)
            counted |= quant
        if counted:
            counted.with_context(pharma_gap_reason="cycle_count").action_apply_inventory()
            self.stats["inventaires_tournants"] += 1

    def patient_returns(self):
        if not self.dispensed or self.rng.random() > 0.35:
            return
        rx = self.env["pharma.prescription"].browse(self.rng.choice(self.dispensed[-80:]))
        if rx.state != "done":
            return
        try:
            with self.env.cr.savepoint():
                rx._pharma_return(self.rng.choice([
                    "Erreur de dosage", "Traitement arrêté par le médecin", "Doublon de délivrance",
                ]), restock=self.rng.random() < 0.3)
                self.stats["retours"] += 1
        except (UserError, ValidationError) as exc:
            _logger.warning("Retour impossible (%s) : %s", rx.name, exc)

    # ------------------------------------------------------------------
    # Encaissements et règlements
    # ------------------------------------------------------------------

    def journals(self):
        if not hasattr(self, "_journals"):
            Journal = self.env["account.journal"]
            domain = [("company_id", "=", self.company.id)]
            bank = Journal.search(domain + [("type", "=", "bank")], limit=1)
            cash = Journal.search(domain + [("type", "=", "cash")], limit=1) or bank
            self._journals = (bank, cash)
        return self._journals

    def pay(self, move, amount, journal):
        if not journal or amount <= 0.0:
            return
        try:
            with self.env.cr.savepoint():
                self.env["account.payment.register"].with_context(
                    active_model="account.move", active_ids=move.ids,
                ).create({
                    "payment_date": fields.Date.today(),
                    "journal_id": journal.id,
                    "amount": round(amount, 2),
                    "payment_difference_handling": "open",
                })._create_payments()
                self.stats["paiements"] += 1
        except (UserError, ValidationError) as exc:
            _logger.warning("Paiement impossible (%s) : %s", move.name, exc)

    def settle(self, day):
        """Encaissements : comptoir le jour même, AMO sous 3 à 6 jours, AMC sous 8 à
        30 jours, avec quelques rejets partiels (créances restant ouvertes).
        Règlements fournisseurs : grossistes le 10 du mois suivant, laboratoire à
        60 jours, parapharmacie à 30 jours."""
        bank, cash = self.journals()
        Move = self.env["account.move"]
        open_invoices = Move.search([
            ("company_id", "=", self.company.id), ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"), ("payment_state", "=", "not_paid"),
        ])
        counter = self.company.pharma_counter_partner_id
        for inv in open_invoices:
            rng = random.Random(SEED * 1_000_003 + inv.id)
            age = (day - inv.invoice_date).days
            partner = inv.partner_id
            if partner == counter or partner.pharma_partner_type == "patient":
                self.pay(inv, inv.amount_residual, cash)
            elif partner.pharma_insurer_type == "amo" and age >= rng.randint(3, 6):
                rejected = rng.random() < 0.15
                self.pay(inv, inv.amount_residual * (rng.uniform(0.96, 0.995) if rejected else 1), bank)
            elif partner.pharma_insurer_type == "amc" and age >= rng.randint(8, 30):
                rejected = rng.random() < 0.25
                self.pay(inv, inv.amount_residual * (rng.uniform(0.92, 0.99) if rejected else 1), bank)
        bills = Move.search([
            ("company_id", "=", self.company.id), ("move_type", "=", "in_invoice"),
            ("state", "=", "posted"), ("payment_state", "=", "not_paid"),
        ])
        paid_month = getattr(self, "_wholesalers_paid", None)
        first_after_10 = day.day >= 10 and paid_month != (day.year, day.month)
        for bill in bills:
            partner = bill.partner_id
            age = (day - bill.invoice_date).days
            if partner.pharma_partner_type == "wholesaler":
                previous_month = (bill.invoice_date.year, bill.invoice_date.month) < (day.year, day.month)
                if first_after_10 and previous_month:
                    self.pay(bill, bill.amount_residual, bank)
            elif partner == self.para_supplier and age >= 30:
                self.pay(bill, bill.amount_residual, bank)
            elif age >= 60:
                self.pay(bill, bill.amount_residual, bank)
        if first_after_10:
            self._wholesalers_paid = (day.year, day.month)

    # Fréquentation horaire (heure locale) : pics de fin de matinée et de fin de journée.
    HOURLY_WEIGHTS = {8: 0.4, 9: 1.0, 10: 1.2, 11: 1.45, 12: 1.3, 13: 0.6, 14: 0.75, 15: 0.9,
                      16: 1.05, 17: 1.4, 18: 1.55, 19: 0.6}

    def at_local(self, day, hour, minute=0):
        """Instant UTC (naïf) correspondant à une heure locale de Paris."""
        local = pytz.timezone("Europe/Paris").localize(
            datetime.combine(day, datetime.min.time()) + timedelta(hours=hour, minutes=minute))
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    def random_slot(self, day):
        saturday = day.weekday() == 5
        hours = [h for h in self.HOURLY_WEIGHTS if not (saturday and h < 9)]
        hour = self.rng.choices(hours, [self.HOURLY_WEIGHTS[h] for h in hours])[0]
        low = 30 if hour == 8 else 0
        high = 29 if hour == 19 else 59
        return hour * 60 + self.rng.randint(low, high)

    def simulate_day(self, day, frozen):
        factor = self.activity_factor(day)
        self.emergency, self.emergency_today = {}, set()
        self.sold_today = defaultdict(float)

        # Ouverture : périmés, réceptions, inventaire tournant, commande du matin
        frozen.move_to(self.at_local(day, 8, 0))
        self.destroy_expired()
        self.receive_due(day)
        if day.weekday() == 0:
            self.cycle_count()
        self.refresh_stock_levels()
        frozen.move_to(self.at_local(day, 8, 15))
        self.daily_orders(day)

        # Passages de la journée, répartis selon la fréquentation horaire
        acute = self.poisson(24 * factor)
        counter = self.poisson(20 * factor * (1.3 if day.weekday() == 5 else 1))
        events = []
        for action in (self.chronic_dispensing(day) + self.acute_dispensing(day, acute)
                       + self.counter_sales(counter) + self.health_services(day)):
            events.append((self.random_slot(day), self.rng.random(), action))

        def midday():
            # Livraison du grossiste, dépannages, puis délivrance des promis
            self.receive_due(day)
            if self.emergency:
                if self.place_order(self.backup_wholesaler, self.emergency, day, "Dépannage"):
                    self.stats["depannages"] += 1
                    self.receive_due(day)
                self.emergency = {}
            self.refresh_stock_levels()
            self.deliver_promises(day)

        events.append((12 * 60 + 15, 0.0, midday))
        events.append((17 * 60, 0.0, self.patient_returns))
        for minute, _tie, action in sorted(events, key=lambda e: (e[0], e[1])):
            frozen.move_to(self.at_local(day, minute // 60, minute % 60))
            action()

        # Clôture : bordereaux, encaissements, photo du stock
        frozen.move_to(self.at_local(day, 19, 45))
        moves = self.env["pharma.prescription"]._pharma_invoice_pending(until=fields.Datetime.now())
        self.stats["factures"] += len(moves)
        self.settle(day)
        self.env["pharma.stock.snapshot"]._take_snapshot(on_date=day, company=self.company)
        self.learn_demand()

    # ------------------------------------------------------------------

    def run(self):
        started = time.time()
        self.check()
        self.log("Simulation du %s au %s (graine %s, échelle %s)", self.start, self.end, SEED, SCALE)
        self.dispensed = []
        with freeze_time(datetime.combine(self.start - timedelta(days=1), datetime.min.time())
                         + timedelta(hours=8)) as frozen:
            self.setup_company()
            self.select_assortment()
            self.create_parapharmacy()
            self.create_partners()
            self.create_team()
            self.setup_purchasing()
            self.popularity = dict(self.demand)
            self.build_chronic_plans()
            self.calibrate_demand()
            self.initial_stock()
            self.env.cr.commit()
            for day in self.opening_days():
                self.simulate_day(day, frozen)
                self.env.cr.commit()
                if day.day == 1 or day == self.end or day.weekday() == 5:
                    self.log("%s : %s", day, dict(self.stats))
            self.env["pharma.cash.forecast"]._compute_forecast(on_date=self.today)
        self.env["ir.config_parameter"].sudo().set_param(
            "pharma_fr_demo.generated", fields.Datetime.to_string(fields.Datetime.now()))
        self.env.cr.commit()
        self.log("Terminé en %.0f s : %s", time.time() - started, dict(self.stats))


Simulation(env).run()  # noqa: F821  (env est fourni par le shell Odoo)
