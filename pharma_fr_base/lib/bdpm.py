"""Parseurs des fichiers de la Base de Données Publique des Médicaments (BDPM).

Module en Python pur (aucune dépendance Odoo) pour pouvoir être testé et réutilisé
hors de l'ERP, par exemple dans un pipeline d'analyse de données.

Format des fichiers (source : « Contenu et format des fichiers téléchargeables
dans la BDM », ANSM) :

* fichiers texte, champs séparés par des tabulations, sans en-tête ;
* encodages historiquement mélangés (UTF-8 / Windows-1252) : on décode ligne
  par ligne ;
* dates au format JJ/MM/AAAA ; montants avec virgule décimale.

Fichiers pris en charge :

=========================  ====================================================
CIS_bdpm.txt               spécialités (code CIS)
CIS_CIP_bdpm.txt           présentations (CIP7 / CIP13, prix, remboursement)
CIS_COMPO_bdpm.txt         compositions (substances actives)
CIS_GENER_bdpm.txt         groupes génériques
CIS_CPD_bdpm.txt           conditions de prescription et de délivrance
CIS_CIP_Dispo_Spec.txt     ruptures et tensions d'approvisionnement
CIS_MITM.txt               médicaments d'intérêt thérapeutique majeur
=========================  ====================================================
"""

import re
import unicodedata
from datetime import date

# Noms canoniques des fichiers -> clé interne
FILE_KEYS = {
    "CIS_bdpm": "cis",
    "CIS_CIP_bdpm": "cis_cip",
    "CIS_COMPO_bdpm": "compo",
    "CIS_GENER_bdpm": "gener",
    "CIS_CPD_bdpm": "cpd",
    "CIS_CIP_Dispo_Spec": "dispo",
    "CIS_MITM": "mitm",
}

GENERIC_TYPES = {
    "0": "princeps",
    "1": "generic",
    "2": "generic_posology",
    "4": "generic_substitutable",
}

AVAILABILITY_STATUSES = {
    "1": "shortage",
    "2": "tension",
    "3": "discontinued",
    "4": "restored",
}

REIMBURSEMENT_RATES = ("15", "30", "65", "100")


# ---------------------------------------------------------------------------
# Utilitaires de bas niveau
# ---------------------------------------------------------------------------

def file_key(filename):
    """Retourne la clé interne d'un fichier BDPM d'après son nom, ou None.

    >>> file_key("CIS_CIP_bdpm.txt")
    'cis_cip'
    >>> file_key("dossier/CIS_bdpm.txt")
    'cis'
    """
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    base = base.rsplit(".", 1)[0]
    # On teste les noms les plus longs d'abord (CIS_CIP_bdpm avant CIS_bdpm).
    for name in sorted(FILE_KEYS, key=len, reverse=True):
        if base.upper() == name.upper():
            return FILE_KEYS[name]
    return None


def decode_line(raw):
    """Décode une ligne en UTF-8, avec repli sur Windows-1252."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def iter_rows(content, min_cols=1):
    """Itère sur les lignes d'un fichier BDPM et renvoie des listes de champs.

    ``content`` peut être des ``bytes`` (fichier brut) ou une ``str``.
    Les lignes vides ou ayant moins de ``min_cols`` colonnes sont ignorées.
    """
    if isinstance(content, str):
        lines = content.splitlines()
    else:
        if content.startswith(b"\xef\xbb\xbf"):
            content = content[3:]
        lines = (decode_line(raw) for raw in content.splitlines())
    for line in lines:
        if not line.strip():
            continue
        fields = [clean(value) for value in line.rstrip("\r\n").split("\t")]
        if len(fields) < min_cols:
            continue
        yield fields


def clean(value):
    """Supprime les espaces superflus (y compris insécables)."""
    if value is None:
        return ""
    value = value.replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def get(fields, index):
    """Accès tolérant à une colonne (renvoie '' si absente)."""
    return fields[index] if index < len(fields) else ""


def parse_date(value):
    """'16/03/2011' -> date(2011, 3, 16) ; valeur vide ou invalide -> None."""
    value = clean(value)
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
    if not match:
        return None
    day, month, year = (int(g) for g in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_price(value):
    """Convertit un montant BDPM en float.

    >>> parse_price("24,34")
    24.34
    >>> parse_price("1 234,56")
    1234.56
    >>> parse_price("1,234,56")
    1234.56
    >>> parse_price("") is None
    True
    """
    value = clean(value).replace(" ", "").replace("€", "")
    if not value:
        return None
    if "," in value:
        parts = value.split(",")
        value = "".join(parts[:-1]).replace(".", "") + "." + parts[-1]
    try:
        return float(value)
    except ValueError:
        return None


def parse_rates(value):
    """'65%;100 %' -> ['65', '100'] (taux reconnus uniquement, ordre conservé)."""
    rates = []
    for part in re.split(r"[;,/]", value or ""):
        digits = re.sub(r"[^0-9]", "", part)
        if digits in REIMBURSEMENT_RATES and digits not in rates:
            rates.append(digits)
    return rates


def parse_bool_fr(value):
    return clean(value).lower() in ("oui", "o", "yes", "true", "1")


def normalize(text):
    """Minuscules sans accents, pour les comparaisons textuelles."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return clean(text).lower()


# ---------------------------------------------------------------------------
# Classification réglementaire (conditions de prescription et de délivrance)
# ---------------------------------------------------------------------------

_RE_LIST_1 = re.compile(r"\bliste\s+(i|1)\b")
_RE_LIST_2 = re.compile(r"\bliste\s+(ii|2)\b")


def classify_conditions(conditions):
    """Déduit le statut réglementaire d'une spécialité à partir des lignes du
    fichier CIS_CPD_bdpm.txt.

    Renvoie un dict :

    * ``prescription_list`` : 'narcotic' > 'list_1' > 'list_2' > 'none'
    * ``narcotic_rules`` : prescription soumise aux règles des stupéfiants
      (stupéfiants et « assimilés stupéfiants »)
    * ``hospital_reserved`` : réservé à l'usage hospitalier
    * ``special_prescription`` : prescription restreinte (hospitalière,
      initiale hospitalière, réservée à certains spécialistes...)
    """
    texts = [normalize(c) for c in conditions if c]
    narcotic = any(t.startswith("stupefiant") for t in texts)
    narcotic_rules = narcotic or any("stupefiant" in t for t in texts)
    if narcotic:
        prescription_list = "narcotic"
    elif any(_RE_LIST_1.search(t) for t in texts):
        prescription_list = "list_1"
    elif any(_RE_LIST_2.search(t) for t in texts):
        prescription_list = "list_2"
    else:
        prescription_list = "none"
    hospital_reserved = any("usage hospitalier" in t for t in texts)
    special_prescription = any(
        key in t
        for t in texts
        for key in (
            "prescription hospitaliere",
            "prescription initiale",
            "prescription reservee",
            "surveillance particuliere",
        )
    )
    return {
        "prescription_list": prescription_list,
        "narcotic_rules": narcotic_rules,
        "hospital_reserved": hospital_reserved,
        "special_prescription": special_prescription,
    }


# ---------------------------------------------------------------------------
# Parseurs par fichier
# ---------------------------------------------------------------------------

def parse_specialites(content):
    """CIS_bdpm.txt -> dict {cis: valeurs}."""
    result = {}
    for f in iter_rows(content, min_cols=2):
        cis = f[0]
        if not cis.isdigit():
            continue
        holders = [h.strip() for h in get(f, 10).split(";") if h.strip()]
        result[cis] = {
            "cis_code": cis,
            "name": get(f, 1),
            "pharmaceutical_form": get(f, 2),
            "administration_routes": get(f, 3).replace(";", ", "),
            "amm_status": get(f, 4),
            "amm_procedure": get(f, 5),
            "marketing_status": get(f, 6),
            "amm_date": parse_date(get(f, 7)),
            "bdm_status": get(f, 8),
            "eu_authorisation_number": get(f, 9),
            "holder": ", ".join(holders),
            "main_holder": holders[0] if holders else "",
            "reinforced_monitoring": parse_bool_fr(get(f, 11)),
        }
    return result


def parse_presentations(content):
    """CIS_CIP_bdpm.txt -> dict {cip13: valeurs}.

    Le fichier publié contient selon les versions 11 ou 13 colonnes :
    prix seul, ou prix hors honoraires / prix honoraires inclus / honoraire.
    """
    result = {}
    for f in iter_rows(content, min_cols=7):
        cis, cip7, cip13 = f[0], get(f, 1), get(f, 6)
        if not cis.isdigit() or not cip13.isdigit():
            continue
        rates = parse_rates(get(f, 8))
        if len(f) >= 13:
            price, price_with_fees, fee = (parse_price(get(f, i)) for i in (9, 10, 11))
            indications = get(f, 12)
        else:
            price, price_with_fees, fee = parse_price(get(f, 9)), None, None
            indications = get(f, 10)
        approval = clean(get(f, 7)).lower()
        result[cip13] = {
            "cis_code": cis,
            "cip7": cip7,
            "cip13": cip13,
            "name": get(f, 2),
            "admin_status": get(f, 3),
            "marketing_status": get(f, 4),
            "marketing_date": parse_date(get(f, 5)),
            "community_approval": approval if approval in ("oui", "non") else "unknown",
            "reimbursement_rate": rates[0] if rates else "0",
            "reimbursement_rates_raw": get(f, 8),
            "price_ttc": price or 0.0,
            "price_with_fees": price_with_fees or 0.0,
            "dispensing_fee": fee or 0.0,
            "reimbursement_indications": indications,
        }
    return result


def parse_compositions(content):
    """CIS_COMPO_bdpm.txt -> dict {cis: [lignes de composition]}."""
    result = {}
    for f in iter_rows(content, min_cols=4):
        cis = f[0]
        if not cis.isdigit():
            continue
        nature = get(f, 6).upper()
        link = get(f, 7)
        result.setdefault(cis, []).append({
            "element": get(f, 1),
            "substance_code": get(f, 2),
            "substance_name": get(f, 3),
            "dosage": get(f, 4),
            "dosage_reference": get(f, 5),
            "nature": nature if nature in ("SA", "FT", "ST") else "SA",
            "link_number": int(link) if link.isdigit() else 0,
        })
    return result


def parse_generic_groups(content):
    """CIS_GENER_bdpm.txt -> (groupes {id: libellé}, membres {cis: infos})."""
    groups, members = {}, {}
    for f in iter_rows(content, min_cols=4):
        group_id, label, cis = f[0], get(f, 1), get(f, 2)
        if not cis.isdigit():
            continue
        groups.setdefault(group_id, label)
        sort = get(f, 4)
        members[cis] = {
            "group_code": group_id,
            "generic_type": GENERIC_TYPES.get(get(f, 3), "generic"),
            "generic_sort": int(sort) if sort.isdigit() else 0,
        }
    return groups, members


def parse_conditions(content):
    """CIS_CPD_bdpm.txt -> dict {cis: [conditions]}."""
    result = {}
    for f in iter_rows(content, min_cols=2):
        cis = f[0]
        if cis.isdigit() and f[1]:
            result.setdefault(cis, []).append(f[1])
    return result


def parse_availability(content):
    """CIS_CIP_Dispo_Spec.txt -> dict {cis: dernier statut connu}.

    Si plusieurs lignes concernent une même spécialité, on garde la plus
    récente (date de mise à jour, puis date de début).
    """
    result = {}
    for f in iter_rows(content, min_cols=4):
        cis = f[0]
        status = AVAILABILITY_STATUSES.get(get(f, 2))
        if not cis.isdigit() or not status:
            continue
        start = parse_date(get(f, 4))
        updated = parse_date(get(f, 5)) or start
        entry = {
            "availability_status": status,
            "availability_date": start,
            "availability_update": updated,
            "availability_restore_date": parse_date(get(f, 6)),
            "availability_url": get(f, 7),
            "cip13": get(f, 1),
        }
        previous = result.get(cis)
        key = (updated or date.min, start or date.min)
        if previous is None or key >= (
            previous["availability_update"] or date.min,
            previous["availability_date"] or date.min,
        ):
            result[cis] = entry
    return result


def parse_mitm(content):
    """CIS_MITM.txt -> dict {cis: code ATC}."""
    result = {}
    for f in iter_rows(content, min_cols=2):
        if f[0].isdigit():
            result[f[0]] = get(f, 1)
    return result
