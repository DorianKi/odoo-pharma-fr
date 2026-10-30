-- Page « Patients », évolution : patients actifs, nouveaux et partis chaque mois,
-- et la marge annuelle qui part avec eux.
with actifs as (
    select d.debut_mois, d.mois, count(distinct p.patient_key) as patients_actifs,
           count(*) as passages, sum(p.marge) as marge
    from {{ ref('fct_passage') }} as p
    join {{ ref('dim_date') }} as d on d.jour = p.jour
    join {{ ref('mart_patients') }} as mp on mp.patient_key = p.patient_key
    where not p.est_retourne and not mp.est_anonyme
    group by d.debut_mois, d.mois
),
arrivees as (
    select d.mois, count(*) as nouveaux_patients
    from {{ ref('mart_patients') }} as mp
    join {{ ref('dim_date') }} as d on d.jour = mp.premier_passage
    where not mp.est_anonyme
    group by d.mois
),
departs as (
    select
        d.mois,
        count(*) as patients_partis,
        sum(mp.marge_annuelle_estimee) as marge_annuelle_partie,
        countif(mp.manquants_avant_dernier_passage > 0) as partis_apres_manquant
    from {{ ref('mart_patients') }} as mp
    join {{ ref('dim_date') }} as d on d.jour = mp.dernier_passage
    where mp.statut_fidelite = 'Perdu'
    group by d.mois
)
select
    a.debut_mois, a.mois, a.patients_actifs, a.passages, a.marge,
    coalesce(n.nouveaux_patients, 0) as nouveaux_patients,
    coalesce(dp.patients_partis, 0) as patients_partis,
    coalesce(dp.marge_annuelle_partie, 0) as marge_annuelle_partie,
    coalesce(dp.partis_apres_manquant, 0) as partis_apres_manquant
from actifs as a
left join arrivees as n on n.mois = a.mois
left join departs as dp on dp.mois = a.mois
