-- Page « Patients » : un patient par ligne, son historique, son statut de fidélité et
-- les manquants qu'il a subis (vision croisée stock × patientèle).
with reference as (
    select max(jour) as date_reference from {{ ref('fct_passage') }}
),
passages as (
    select
        patient_key,
        min(jour) as premier_passage,
        max(jour) as dernier_passage,
        count(*) as passages,
        countif(type_vente = 'Ordonnance') as ordonnances,
        sum(ca_ttc) as ca_ttc,
        sum(marge) as marge,
        logical_or(renouvellement > 0) as est_chronique
    from {{ ref('fct_passage') }}
    where not est_retourne and patient_key is not null
    group by patient_key
),
manquants as (
    select
        m.patient_key,
        count(*) as manquants,
        countif(m.jour >= date_sub(p.dernier_passage, interval 60 day)) as manquants_avant_dernier_passage
    from {{ ref('fct_manquant') }} as m
    join passages as p on p.patient_key = m.patient_key
    group by m.patient_key
),
missions as (
    select patient_key, count(*) as missions, sum(montant) as ca_missions
    from {{ ref('fct_mission') }}
    group by patient_key
),
detail as (
    select
        p.*,
        dp.tranche_age,
        dp.regime,
        dp.code_postal,
        dp.a_complementaire,
        dp.est_anonyme,
        date_diff(r.date_reference, p.dernier_passage, day) as jours_depuis_dernier_passage,
        date_diff(r.date_reference, p.premier_passage, day) as anciennete_jours,
        case when p.passages > 1
             then date_diff(p.dernier_passage, p.premier_passage, day) / (p.passages - 1)
        end as rythme_jours,
        coalesce(m.manquants, 0) as manquants,
        coalesce(m.manquants_avant_dernier_passage, 0) as manquants_avant_dernier_passage,
        coalesce(mi.missions, 0) as missions,
        coalesce(mi.ca_missions, 0) as ca_missions,
        r.date_reference
    from passages as p
    cross join reference as r
    left join {{ ref('dim_patient') }} as dp on dp.patient_key = p.patient_key
    left join manquants as m on m.patient_key = p.patient_key
    left join missions as mi on mi.patient_key = p.patient_key
)
select
    d.*,
    case
        when d.est_anonyme then 'Client de passage'
        when d.premier_passage >= date_sub(d.date_reference, interval 30 day) then 'Nouveau'
        when d.est_chronique and d.jours_depuis_dernier_passage > 60 then 'Perdu'
        when d.est_chronique and d.jours_depuis_dernier_passage > 40 then 'À risque'
        when d.jours_depuis_dernier_passage > 120 then 'Perdu'
        else 'Actif'
    end as statut_fidelite,
    d.marge * 365 / greatest(d.anciennete_jours, 30) as marge_annuelle_estimee
from detail as d
