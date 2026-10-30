select
    id as produit_id,
    cip13,
    name as libelle,
    case category
        when 'drug_reimbursed' then 'Médicament remboursable'
        when 'drug_otc' then 'Médicament non remboursable'
        when 'parapharmacy' then 'Parapharmacie'
        when 'medical_device' then 'Dispositif médical'
        else 'Autre'
    end as rayon,
    coalesce(laboratory, 'Non renseigné') as laboratoire,
    case generic_type
        when 'princeps' then 'Princeps'
        when 'generic' then 'Générique'
        when 'generic_posology' then 'Générique'
        when 'generic_substitutable' then 'Générique'
        else 'Hors répertoire'
    end as statut_generique,
    generic_group as groupe_generique,
    generic_group is not null as est_substituable,
    safe_cast(reimbursement_rate as int64) as taux_remboursement,
    safe_cast(vat_rate as float64) as taux_tva,
    coalesce(public_price, list_price) as prix_public_ttc,
    coalesce(is_narcotic, false) as est_stupefiant,
    prescription_list as liste,
    availability_status as disponibilite_nationale,
    is_fee as est_honoraire
from {{ source('pharma_raw', 'product') }}
