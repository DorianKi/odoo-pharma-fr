-- Requêtes d'exemple sur la base PostgreSQL d'Odoo (modules odoo-pharma-fr).
-- Les noms d'articles sont traduisibles : stockés en JSON, d'où name->>'fr_FR' / 'en_US'.

-- 1. Articles officine : catégorie, TVA, prix public, laboratoire
SELECT COALESCE(pt.name->>'fr_FR', pt.name->>'en_US') AS article,
       pp.barcode            AS cip13,
       pt.pharma_category    AS categorie,
       pt.pharma_vat_rate    AS tva,
       pt.pharma_public_price AS prix_public_ttc,
       lab.name              AS laboratoire
FROM product_template pt
JOIN product_product pp ON pp.product_tmpl_id = pt.id
LEFT JOIN res_partner lab ON lab.id = pt.pharma_laboratory_id
WHERE pt.pharma_category IS NOT NULL
ORDER BY article;

-- 2. Stock par lot avec date de péremption et valeur au coût
SELECT COALESCE(pt.name->>'fr_FR', pt.name->>'en_US') AS article,
       lot.name AS lot,
       lot.expiration_date::date AS peremption,
       SUM(q.quantity) AS quantite,
       ROUND(SUM(q.quantity * COALESCE((pp.standard_price->>(q.company_id::text))::numeric, 0)), 2) AS valeur
FROM stock_quant q
JOIN stock_location loc ON loc.id = q.location_id AND loc.usage = 'internal'
JOIN product_product pp ON pp.id = q.product_id
JOIN product_template pt ON pt.id = pp.product_tmpl_id
LEFT JOIN stock_lot lot ON lot.id = q.lot_id
GROUP BY 1, 2, 3
ORDER BY peremption NULLS LAST;

-- 3. Activité quotidienne : ordonnances, CA, honoraires, marge, parts payeurs
SELECT dispensing_date::date AS jour,
       COUNT(*)              AS ordonnances,
       SUM(amount_total)     AS ca_ttc,
       SUM(amount_untaxed)   AS ca_ht,
       SUM(amount_fees)      AS honoraires_ttc,
       SUM(margin)           AS marge_brute_ht,
       SUM(amount_amo)       AS part_amo,
       SUM(amount_amc)       AS part_amc,
       SUM(amount_patient)   AS reste_a_charge
FROM pharma_prescription
WHERE state = 'done'
GROUP BY 1
ORDER BY 1 DESC;

-- 4. Taux de substitution générique par mois
SELECT date_trunc('month', dispensing_date)::date AS mois,
       SUM(generic_count)::numeric / NULLIF(SUM(substitutable_count), 0) AS taux_generiques
FROM pharma_prescription
WHERE state = 'done'
GROUP BY 1
ORDER BY 1;

-- 5. Achats par fournisseur : remises et prix net net
SELECT p.name AS fournisseur,
       po.pharma_order_type AS type_commande,
       COUNT(DISTINCT po.id) AS commandes,
       ROUND(SUM(pol.price_subtotal), 2) AS achats_ht,
       ROUND(AVG(pol.discount), 2) AS remise_moyenne,
       ROUND(SUM(pol.pharma_net_price_unit * pol.product_qty), 2) AS cout_net_net
FROM purchase_order_line pol
JOIN purchase_order po ON po.id = pol.order_id AND po.state = 'purchase'
JOIN res_partner p ON p.id = po.partner_id
GROUP BY 1, 2
ORDER BY achats_ht DESC;

-- 6. Registre des stupéfiants (dernier solde par produit)
SELECT DISTINCT ON (r.product_id)
       COALESCE(pt.name->>'fr_FR', pt.name->>'en_US') AS stupefiant,
       r.date, r.kind AS derniere_operation, r.balance AS stock
FROM pharma_narcotic_register r
JOIN product_product pp ON pp.id = r.product_id
JOIN product_template pt ON pt.id = pp.product_tmpl_id
ORDER BY r.product_id, r.number DESC;

-- 7. Ruptures nationales (ANSM) sur les articles référencés
SELECT COALESCE(pt.name->>'fr_FR', pt.name->>'en_US') AS article,
       s.availability_status AS statut, s.availability_date AS depuis
FROM product_template pt
JOIN pharma_specialite s ON s.id = pt.pharma_specialite_id
WHERE s.availability_status IN ('shortage', 'tension');
