# Entrepôt de données : Odoo → BigQuery → dbt → Looker Studio

Le pharmacien reprend la main sur ses données. Chaque soir, elles sortent d'Odoo,
pseudonymisées, vers un entrepôt BigQuery qu'il possède. dbt les y transforme en modèle
en étoile documenté et testé. Le tableau de bord ne lit que cet entrepôt, jamais Odoo :
changer de logiciel de gestion ne demanderait de réécrire que l'export.

```
Odoo (PostgreSQL, sur le poste)
  │  scripts/export_raw.py      pseudonymisation des patients, CSV + schémas
  ▼
BigQuery  pharma_raw            copie brute, rechargée chaque nuit (scripts/load_bigquery.sh)
  │  dbt build
  ▼
pharma_staging  (vues)          renommage en français, heures de Paris
pharma_core     (tables)        modèle en étoile : 6 dimensions, 11 faits
pharma_mart     (tables)        15 tables prêtes pour le tableau de bord
  │
  ▼
Looker Studio                   tableau de bord en 4 pages : Journée, Stock, Argent, Patients
```

## Le modèle en étoile (`pharma_core`)

| Table | Grain | Contenu |
|---|---|---|
| `dim_date` | jour | calendrier, jour de la semaine, mois, jour ouvré |
| `dim_produit` | article | rayon, laboratoire, princeps / générique, groupe générique, prix |
| `dim_patient` | patient | clé pseudonyme, tranche d'âge, régime (ALD, C2S), complémentaire |
| `dim_prescripteur` | médecin | RPPS, spécialité |
| `dim_vendeur` | membre de l'équipe | nom, pharmacien ou non |
| `dim_partenaire` | fournisseur ou payeur | type, délai de paiement attendu, franco |
| `fct_passage` | passage en caisse | CA, marge (honoraires compris), parts AMO / AMC / patient, heure, vendeur |
| `fct_vente_ligne` | article vendu | quantité, CA, marge, substitution générique |
| `fct_stock_jour` | article × jour | stock, valeur, couverture, surstock, péremptions, ruptures |
| `fct_achat_ligne` | ligne de commande | fournisseur, remise, dépannage |
| `fct_facture` | facture | échéance, date et délai réels de paiement |
| `fct_tresorerie_jour` | jour | encaissements par payeur, décaissements, solde |
| `fct_manquant` | demande non servie | promis ou vente perdue, délai, chiffre perdu |
| `fct_mission` | mission de santé | type, pharmacien, montants |
| `fct_ecart_inventaire` | écart d'inventaire | démarque inconnue valorisée |
| `fct_prevision_tresorerie` | jour à venir | prévision à 60 jours |

Les **faits journaliers** (`fct_stock_jour`, `fct_tresorerie_jour`, `fct_prevision_tresorerie`)
donnent l'historique jour par jour que l'ERP ne garde pas.

Le dictionnaire complet de chaque colonne est généré par `dbt docs generate` puis
`dbt docs serve`, avec le graphe des dépendances.

## Données de santé

- Aucun nom, NIR, adresse ni date de naissance de patient ne quitte le poste. Le patient
  devient une clé HMAC-SHA256 calculée avec une clé secrète conservée localement
  (`.pseudo_key`, non versionnée). Restent seulement l'année de naissance, le code postal
  et le régime.
- Un test dbt (`assert_patient_pseudonymise`) vérifie qu'aucune clé ne ressemble à un NIR.
- Les données sont hébergées dans l'Union européenne (`location: EU`).
- Pour une vraie officine, des données de santé doivent être hébergées chez un hébergeur
  certifié HDS : à vérifier pour l'offre Google Cloud retenue avant tout usage réel.

## Mise en place (une fois)

1. **Projet Google Cloud** : sur [console.cloud.google.com](https://console.cloud.google.com),
   créez un projet (par exemple `pharmacie-data`) et ouvrez BigQuery. Sans carte bancaire,
   le projet est en « bac à sable » : 10 Go de stockage et 1 To de requêtes par mois
   gratuits ; les tables expirent après 60 jours, ce qui ne gêne pas puisqu'elles sont
   recréées chaque nuit.
2. **Google Cloud SDK** sur le Mac : `brew install --cask google-cloud-sdk`, puis
   `gcloud auth login` et `gcloud auth application-default login` (ouverture du
   navigateur ; aucun mot de passe n'est stocké dans le dépôt).
3. **Outils Python** (dans le dossier du dépôt) :
   ```bash
   python3 -m venv .venv-warehouse && source .venv-warehouse/bin/activate
   pip install -r requirements-warehouse.txt
   ```
4. **Profil dbt** : `mkdir -p ~/.dbt && cp dbt/profiles.example.yml ~/.dbt/profiles.yml`.
5. **Identifiant du projet** : `export GCP_PROJECT=pharmacie-data` (à mettre dans
   `~/.zshrc` pour ne pas le retaper).

## Chaque soir (ou après une génération de données)

```bash
source .venv-warehouse/bin/activate
./scripts/pipeline.sh pharmacie2        # export → BigQuery → dbt build (modèles + tests)
```

Étapes séparées si besoin :

```bash
python3 scripts/export_raw.py --dbname pharmacie2 --out export/
./scripts/load_bigquery.sh export/
cd dbt && dbt build          # puis : dbt docs generate && dbt docs serve
```

## Vérifier sans Google Cloud

`scripts/dbt_check_local.py` charge l'export dans un PostgreSQL local, traduit les modèles
BigQuery en PostgreSQL (sqlglot) et exécute tous les tests déclarés. Il sert de filet de
sécurité pendant le développement ; en production, c'est `dbt build` sur BigQuery qui fait foi.

```bash
docker compose exec db createdb -U odoo warehouse_check
PGPORT=55432 python3 scripts/dbt_check_local.py --export export/
```
