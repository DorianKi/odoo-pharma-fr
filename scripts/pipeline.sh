#!/usr/bin/env bash
# Chaîne complète, à lancer chaque soir après la clôture (ou après une génération) :
#   1. export pseudonymisé d'Odoo   2. chargement dans BigQuery   3. dbt build (modèles + tests)
#
#   GCP_PROJECT=mon-projet ./scripts/pipeline.sh pharmacie2
set -euo pipefail

DBNAME="${1:?Usage : pipeline.sh <base Odoo>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python3 scripts/export_raw.py --dbname "$DBNAME" --out export/
./scripts/load_bigquery.sh export/
cd dbt
dbt build --profiles-dir "${DBT_PROFILES_DIR:-$HOME/.dbt}"
