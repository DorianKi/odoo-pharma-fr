#!/usr/bin/env bash
# Charge les CSV produits par export_raw.py dans BigQuery (dataset pharma_raw, région EU).
# Chaque table est remplacée en entier : l'historique complet est réexporté chaque nuit,
# ce qui reste léger pour une officine (quelques dizaines de Mo).
#
#   GCP_PROJECT=mon-projet ./scripts/load_bigquery.sh export/
#
# Prérequis : Google Cloud SDK (commande bq) et `gcloud auth login`.
set -euo pipefail

: "${GCP_PROJECT:?Renseignez GCP_PROJECT avec l'identifiant de votre projet Google Cloud}"
EXPORT_DIR="${1:-export}"
DATASET="pharma_raw"
LOCATION="EU"

if ! bq --project_id="$GCP_PROJECT" show --dataset "$GCP_PROJECT:$DATASET" >/dev/null 2>&1; then
    bq --project_id="$GCP_PROJECT" --location="$LOCATION" mk --dataset \
        --description "Données brutes exportées d'Odoo, pseudonymisées" "$GCP_PROJECT:$DATASET"
fi

for schema in "$EXPORT_DIR"/*.schema.json; do
    table="$(basename "$schema" .schema.json)"
    echo "→ $DATASET.$table"
    bq --project_id="$GCP_PROJECT" --location="$LOCATION" load --quiet --replace \
        --source_format=CSV --skip_leading_rows=1 --allow_quoted_newlines \
        "$DATASET.$table" "$EXPORT_DIR/$table.csv" "$schema"
done
echo "Chargement terminé."
