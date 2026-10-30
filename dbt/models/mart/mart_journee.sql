-- Page « Journée » : un jour par ligne, toutes les dimensions de l'officine côte à côte,
-- avec le même jour de la semaine précédente pour comparer.
with reference as (
    select max(jour) as date_reference from {{ ref('fct_passage') }}
),
ventes as (
    select
        jour,
        count(*) as passages,
        countif(type_vente = 'Ordonnance') as ordonnances,
        countif(type_vente = 'Comptoir') as ventes_comptoir,
        count(distinct patient_key) as patients,
        sum(ca_ttc) as ca_ttc,
        sum(ca_ht) as ca_ht,
        sum(marge) as marge,
        sum(honoraires_ttc) as honoraires_ttc,
        sum(part_amo) as part_amo,
        sum(part_amc) as part_amc,
        sum(part_patient) as part_patient
    from {{ ref('fct_passage') }}
    where not est_retourne
    group by jour
),
missions as (
    select jour, count(*) as missions, sum(montant) as ca_missions
    from {{ ref('fct_mission') }}
    group by jour
),
manquants as (
    select
        jour,
        count(*) as manquants,
        countif(issue = 'Vente perdue') as ventes_perdues,
        sum(ca_perdu_ttc) as ca_perdu_ttc
    from {{ ref('fct_manquant') }}
    group by jour
),
stock as (
    select
        jour,
        sum(valeur) as valeur_stock,
        countif(est_en_rupture) as articles_en_rupture,
        sum(valeur_perime_90j) as valeur_perime_90j,
        sum(valeur_surstock) as valeur_surstock,
        sum(valeur_dormante) as valeur_dormante
    from {{ ref('fct_stock_jour') }}
    group by jour
),
achats as (
    select
        jour,
        sum(montant_ht) as achats_ht,
        count(distinct case when est_depannage then commande_id end) as depannages
    from {{ ref('fct_achat_ligne') }}
    group by jour
),
ecarts as (
    select jour, sum(ecart_valeur) as ecart_inventaire
    from {{ ref('fct_ecart_inventaire') }}
    group by jour
),
base as (
    select
        d.jour, d.jour_semaine, d.jour_semaine_num, d.mois, d.debut_semaine, d.est_ouvre,
        coalesce(v.passages, 0) as passages,
        coalesce(v.ordonnances, 0) as ordonnances,
        coalesce(v.ventes_comptoir, 0) as ventes_comptoir,
        coalesce(v.patients, 0) as patients,
        coalesce(v.ca_ttc, 0) as ca_ttc,
        coalesce(v.ca_ht, 0) as ca_ht,
        coalesce(v.marge, 0) as marge,
        coalesce(v.honoraires_ttc, 0) as honoraires_ttc,
        coalesce(v.part_amo, 0) as part_amo,
        coalesce(v.part_amc, 0) as part_amc,
        coalesce(v.part_patient, 0) as part_patient,
        coalesce(mi.missions, 0) as missions,
        coalesce(mi.ca_missions, 0) as ca_missions,
        coalesce(ma.manquants, 0) as manquants,
        coalesce(ma.ventes_perdues, 0) as ventes_perdues,
        coalesce(ma.ca_perdu_ttc, 0) as ca_perdu_ttc,
        s.valeur_stock,
        s.articles_en_rupture,
        s.valeur_perime_90j,
        s.valeur_surstock,
        s.valeur_dormante,
        coalesce(a.achats_ht, 0) as achats_ht,
        coalesce(a.depannages, 0) as depannages,
        coalesce(e.ecart_inventaire, 0) as ecart_inventaire,
        t.entrees,
        t.sorties,
        t.solde as solde_tresorerie
    from {{ ref('dim_date') }} as d
    cross join reference as r
    left join ventes as v on v.jour = d.jour
    left join missions as mi on mi.jour = d.jour
    left join manquants as ma on ma.jour = d.jour
    left join stock as s on s.jour = d.jour
    left join achats as a on a.jour = d.jour
    left join ecarts as e on e.jour = d.jour
    left join {{ ref('fct_tresorerie_jour') }} as t on t.jour = d.jour
    where d.jour <= r.date_reference
)
select
    b.*,
    b.jour = r.date_reference as est_dernier_jour,
    safe_divide(b.ca_ttc, b.passages) as panier_moyen_ttc,
    safe_divide(b.marge, b.ca_ht) as taux_marge,
    s7.passages as passages_s_1,
    s7.ca_ttc as ca_ttc_s_1,
    s7.marge as marge_s_1
from base as b
cross join reference as r
left join base as s7 on s7.jour = date_sub(b.jour, interval 7 day)
