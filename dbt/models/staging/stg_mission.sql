select
    id as mission_id,
    date(date, '{{ var("fuseau") }}') as jour,
    type_code as code_mission,
    type_name as type_mission,
    case category
        when 'vaccination' then 'Vaccination'
        when 'test' then 'Dépistage'
        when 'review' then 'Bilan de médication'
        when 'interview' then 'Entretien'
        else coalesce(category, 'Autre')
    end as categorie,
    patient_key,
    pharmacist_id as pharmacien_id,
    duration_minutes as duree_minutes,
    amount_total as montant,
    amount_amo as part_amo,
    amount_amc as part_amc,
    amount_patient as part_patient
from {{ source('pharma_raw', 'health_service') }}
where state = 'done'
