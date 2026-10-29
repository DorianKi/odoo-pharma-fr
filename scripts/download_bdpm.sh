#!/usr/bin/env bash
# Télécharge les fichiers de la Base de Données Publique des Médicaments (BDPM).
#
# Usage : ./scripts/download_bdpm.sh [répertoire_cible]   (défaut : ./bdpm)
#
# Les fichiers peuvent ensuite être importés :
#   - via Odoo : Pharmacie > Configuration > Import BDPM (zip ou fichiers) ;
#   - ou automatiquement : paramètre système pharma_fr_base.bdpm_directory
#     pointant sur ce répertoire + tâche planifiée « mise à jour de la base BDPM ».
#
# Source : base de données publique des médicaments
# https://base-donnees-publique.medicaments.gouv.fr (licence : réutilisation libre
# avec mention de la source et de la date de mise à jour).
set -euo pipefail

TARGET="${1:-bdpm}"
BASE_URL="https://base-donnees-publique.medicaments.gouv.fr/download/file"
FILES=(
  CIS_bdpm.txt
  CIS_CIP_bdpm.txt
  CIS_COMPO_bdpm.txt
  CIS_GENER_bdpm.txt
  CIS_CPD_bdpm.txt
  CIS_CIP_Dispo_Spec.txt
  CIS_MITM.txt
)

mkdir -p "$TARGET"
for file in "${FILES[@]}"; do
  echo "→ $file"
  curl -fsSL --retry 3 -o "$TARGET/$file.tmp" "$BASE_URL/$file"
  mv "$TARGET/$file.tmp" "$TARGET/$file"
done

(cd "$TARGET" && zip -q -j bdpm.zip "${FILES[@]}" 2>/dev/null) || true
date -u +"%Y-%m-%dT%H:%M:%SZ" > "$TARGET/DATE_TELECHARGEMENT.txt"
echo "Fichiers BDPM téléchargés dans $TARGET/"
