# Projet dbt `pharma_dbt`

Transforme les tables brutes exportées d'Odoo (`pharma_raw`) en trois couches BigQuery :

| Couche | Dataset | Matérialisation | Rôle |
|---|---|---|---|
| `models/staging` | `pharma_staging` | vues | une vue par table brute : noms en français, heures de Paris, libellés lisibles |
| `models/core` | `pharma_core` | tables | modèle en étoile : `dim_*` (6 dimensions) et `fct_*` (11 faits) |
| `models/mart` | `pharma_mart` | tables | tables prêtes pour Looker Studio, une par usage du tableau de bord |

Commandes (depuis ce dossier, environnement `.venv-warehouse` activé) :

```bash
dbt debug                 # vérifie la connexion à BigQuery
dbt build                 # construit les modèles et exécute les tests
dbt docs generate && dbt docs serve   # dictionnaire de données et graphe des dépendances
```

Tests : clés uniques et non nulles, valeurs autorisées, relations entre faits et dimensions
(fichiers `_*.yml`), et contrôles métier dans `tests/` : CA de la page Journée égal à la
somme des passages, solde de trésorerie égal à la somme des mouvements, classe A portant
au moins 80 % de la marge, aucune clé patient ressemblant à un NIR.

Conventions : SQL BigQuery standard, minuscules, une CTE par étape, noms de colonnes en
français, montants en euros (`ca_ttc`, `ca_ht`, `marge`), la date de référence d'une analyse
est le dernier jour de ventes (pas la date du jour), pour que des données de démonstration
restent cohérentes.
