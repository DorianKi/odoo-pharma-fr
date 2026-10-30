# Tableau de bord Looker Studio : Journée, Stock, Argent, Patients

Quatre pages, une seule règle : chaque chiffre se relie aux deux autres axes. Un article
en surstock montre aussi qui l'achète et ce qu'il rapporte. Un patient parti montre aussi
ce qu'il achetait et les manquants qu'il a subis.

Toutes les sources sont des tables `pharma_mart` (jamais Odoo, jamais `pharma_core`).

## 1. Créer le rapport et les sources

1. [lookerstudio.google.com](https://lookerstudio.google.com) → **Créer → Rapport** →
   connecteur **BigQuery** → votre projet → `pharma_mart` → `mart_journee`.
2. **Ressource → Gérer les sources de données ajoutées → Ajouter** pour chacune :
   `mart_ventes`, `mart_produits`, `mart_stock_jour`, `mart_tresorerie`, `mart_payeurs`,
   `mart_patients`, `mart_patients_mois`, `mart_manquants`, `mart_affluence`,
   `mart_equipe`, `mart_generiques`, `mart_achats`.
3. Dans chaque source, passez les montants (`ca_*`, `marge*`, `valeur*`, `solde`, `part_*`)
   au type **Devise (EUR)** et les colonnes `taux_*` au type **Pourcentage**.
4. **Champs calculés** à créer dans la source indiquée (ne jamais moyenner une colonne de taux) :

| Source | Champ | Formule |
|---|---|---|
| mart_journee | Taux de marge | `SUM(marge) / SUM(ca_ht)` |
| mart_journee | Panier moyen | `SUM(ca_ttc) / SUM(passages)` |
| mart_journee | Évolution CA sur S-1 | `(SUM(ca_ttc) - SUM(ca_ttc_s_1)) / SUM(ca_ttc_s_1)` |
| mart_ventes | Taux de marge | `SUM(marge) / SUM(ca_ht)` |
| mart_ventes | Part générique | `SUM(CASE WHEN est_generique THEN 1 ELSE 0 END) / COUNT(ligne_id)` |
| mart_generiques | Taux de substitution | `SUM(lignes_generiques) / SUM(lignes_substituables)` |

## 2. Filtres communs à toutes les pages

En haut de la première page, ajoutez ces commandes, puis **clic droit → Définir au niveau
du rapport** pour qu'elles s'appliquent partout et suivent l'utilisateur de page en page :

- **Période** : commande de plage de dates (champ `jour`), défaut « 30 derniers jours » ;
- listes déroulantes : **Rayon**, **Laboratoire**, **Classe ABC**, **Statut de fidélité**,
  **Tranche d'âge**, **Vendeur**.

Les tables mart utilisent volontairement les mêmes noms de colonnes (`jour`, `mois`, `rayon`,
`laboratoire`, `classe_abc`, `statut_fidelite`, `tranche_age`, `vendeur`). Une commande
filtre les graphiques d'une autre source seulement si l'**identifiant de champ** est le même :
vérifiez-le dans **Ressource → Gérer les noms et ID des champs** et unifiez-le si besoin
(un même identifiant, par exemple `rayon`, pour le champ de chaque source).

Activez le **filtrage croisé** (onglet Configuration de chaque graphique, « Interactions ») :
un clic sur une barre ou une ligne filtre les autres graphiques de la page.

## 3. Page « Journée » (ce matin)

Question : comment s'est passée la journée d'hier, et qu'est-ce qui demande une action ?

| Élément | Source | Configuration |
|---|---|---|
| 8 indicateurs | mart_journee | filtre `est_dernier_jour = vrai` ; CA TTC (comparaison : `ca_ttc_s_1`), marge, taux de marge, passages, panier moyen, manquants, missions, solde de trésorerie |
| Courbe 30 jours | mart_journee | dimension `jour`, mesures CA TTC et marge, filtre `est_ouvre` |
| Affluence d'hier | mart_affluence | barres par `heure`, mesure `passages`, plus `vendeurs_actifs` en ligne |
| Manquants d'hier | mart_manquants | tableau : article, raison, issue, statut, CA perdu, statut du patient |
| Équipe d'hier | mart_equipe | tableau : vendeur, passages, CA, marge, lignes de conseil, missions |
| Alertes stock | mart_produits | tableau filtré `est_en_rupture` ou `valeur_perime_90j > 0` |

## 4. Page « Stock »

Question : où est immobilisé mon argent, et qu'est-ce qui manque ?

| Élément | Source | Configuration |
|---|---|---|
| 6 indicateurs | mart_produits | valeur du stock, surstock, périme sous 90 jours, dormant, articles en rupture, ruptures nationales |
| Stock par rayon | mart_produits | barres empilées : `rayon` × `classe_abc`, mesure `stock_valeur` |
| Évolution | mart_stock_jour | courbe : `jour`, mesures `valeur`, `valeur_surstock` |
| Articles à traiter | mart_produits | tableau trié par surstock : article, rayon, classe ABC, stock, couverture, surstock, GMROI, manquants 30 j, **patients 90 j**, **marge 90 j** |
| Qui achète ces articles ? | mart_ventes | barres `statut_fidelite` et `tranche_age`, mesure `ca_ttc` (suit la sélection du tableau grâce aux filtres communs) |
| Manquants par rayon | mart_manquants | barres `rayon`, mesure `ca_perdu_ttc`, répartition par `issue` |

## 5. Page « Argent »

Question : combien je gagne, où, et quand l'argent rentre-t-il ?

| Élément | Source | Configuration |
|---|---|---|
| Indicateurs | mart_journee, mart_payeurs | CA, marge et taux du mois ; solde ; créances ouvertes ; encours en retard |
| Trésorerie réelle et prévue | mart_tresorerie | courbe `jour` × `solde`, dimension de répartition `nature` (Réel, Prévision) |
| Encaissements | mart_tresorerie | barres empilées `entree_amo`, `entree_amc`, `entree_autre` par semaine |
| Délais des payeurs | mart_payeurs | tableau : payeur, délai moyen réel, délai attendu, encours, retard |
| Marge par rayon et laboratoire | mart_ventes | barres `rayon` puis `laboratoire`, mesure marge, taux de marge |
| Marge par type de patient | mart_ventes | barres `statut_fidelite`, `regime` (axe patientèle) |
| Génériques par prescripteur | mart_generiques | tableau trié par taux de substitution croissant |
| Achats | mart_achats | tableau des dépannages et des commandes `sous_franco` |

## 6. Page « Patients »

Question : qui sont mes patients, qui part, et pourquoi ?

| Élément | Source | Configuration |
|---|---|---|
| Indicateurs | mart_patients | patients actifs, nouveaux, à risque, perdus ; marge annuelle estimée des perdus ; partis après un manquant |
| Répartition | mart_patients | anneau `statut_fidelite` |
| Évolution mensuelle | mart_patients_mois | barres : actifs, nouveaux, partis ; courbe : marge annuelle partie |
| Patients à rappeler | mart_patients | tableau filtré `statut_fidelite = À risque`, trié par `marge_annuelle_estimee` : clé, tranche d'âge, régime, dernier passage, jours depuis, manquants subis |
| Ce qu'ils achètent | mart_ventes | barres `rayon` et `classe_abc` (axe stock), mesure marge (axe argent) |
| Missions | mart_patients | nombre de missions par statut de fidélité |

La clé patient est pseudonyme : pour retrouver qui rappeler, le pharmacien la cherche dans
le fichier de correspondance gardé sur son poste (voir `export_raw.py --correspondance`),
jamais dans le cloud.

## 7. Partager

**Partager → Inviter** : donnez l'accès en lecture aux membres de l'équipe. Le rapport et
le projet Google Cloud appartiennent au compte de la pharmacie ; un prestataire n'y a
qu'un accès délégué, qu'on peut retirer.
