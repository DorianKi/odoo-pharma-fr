from datetime import datetime, time, timedelta

from odoo import api, fields, models

COVERAGE_NONE = 999.0  # couverture « infinie » : stock sans aucune vente récente


class PharmaStockSnapshot(models.Model):
    """Photo quotidienne du stock, par article.

    Odoo ne conserve que le stock présent ; cette table garde, jour après jour,
    la quantité, la valeur, la demande récente et les risques (péremption,
    dormance, rupture nationale). C'est la base du suivi quotidien et des
    indicateurs de rotation.
    """

    _name = "pharma.stock.snapshot"
    _description = "Photo quotidienne du stock"
    _order = "date desc, value desc"

    date = fields.Date("Date", required=True, index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    product_id = fields.Many2one("product.product", "Article", required=True, index=True)
    product_tmpl_id = fields.Many2one("product.template", "Modèle d'article", index=True)
    pharma_category = fields.Selection(
        [
            ("drug_reimbursed", "Médicament remboursable"),
            ("drug_otc", "Médicament non remboursable"),
            ("parapharmacy", "Parapharmacie"),
            ("medical_device", "Dispositif médical (LPP)"),
            ("other", "Autre"),
        ],
        string="Catégorie", index=True,
    )
    laboratory_id = fields.Many2one("res.partner", "Laboratoire", index=True)
    is_generic = fields.Boolean("Générique")
    quantity = fields.Float("Quantité en stock")
    unit_cost = fields.Float("Coût unitaire", digits="Product Price")
    value = fields.Monetary("Valeur du stock")
    sales_30d = fields.Float("Ventes sur 30 jours")
    daily_demand = fields.Float("Demande moyenne / jour", digits=(12, 3))
    coverage_days = fields.Float(
        "Couverture (jours)", digits=(12, 1),
        help=f"Stock / demande moyenne ; {COVERAGE_NONE:g} si aucune vente sur 30 jours.",
    )
    qty_expiring_90d = fields.Float("Périme sous 90 jours")
    value_expiring_90d = fields.Monetary("Valeur périmant sous 90 jours")
    qty_expired = fields.Float("Périmé en stock")
    last_sale_date = fields.Date("Dernière vente")
    is_dormant = fields.Boolean("Dormant", help="En stock, sans vente depuis 60 jours.")
    is_out_of_stock = fields.Boolean("Rupture officine")
    national_shortage = fields.Boolean("Rupture ou tension nationale")

    _date_product_uniq = models.Constraint(
        "unique (date, product_id, company_id)", "Une seule photo par article et par jour."
    )

    @api.model
    def _take_snapshot(self, on_date=None, company=None):
        """Enregistre la photo du stock de fin de journée (remplace celle du jour)."""
        on_date = on_date or fields.Date.context_today(self)
        companies = company or self.env["res.company"].search([])
        snapshots = self.browse()
        for comp in companies:
            snapshots |= self.with_company(comp)._snapshot_company(on_date, comp)
        return snapshots

    def _snapshot_company(self, on_date, company):
        self.search([("date", "=", on_date), ("company_id", "=", company.id)]).unlink()
        products = self.env["product.product"].with_company(company).search([
            ("pharma_category", "!=", False), ("is_storable", "=", True),
            "|", ("company_id", "=", False), ("company_id", "=", company.id),
        ])
        if not products:
            return self.browse()
        end = datetime.combine(on_date, time.max)
        Quant, Move = self.env["stock.quant"], self.env["stock.move"]
        internal = [("location_id.usage", "=", "internal"), ("company_id", "=", company.id),
                    ("product_id", "in", products.ids)]
        on_hand = dict(Quant._read_group(internal, ["product_id"], ["quantity:sum"]))
        expiring = dict(Quant._read_group(
            internal + [("expiration_date", ">=", end),
                        ("expiration_date", "<", end + timedelta(days=90))],
            ["product_id"], ["quantity:sum"],
        ))
        expired = dict(Quant._read_group(
            internal + [("expiration_date", "<", end)], ["product_id"], ["quantity:sum"],
        ))
        sale_domain = [
            ("product_id", "in", products.ids), ("state", "=", "done"),
            ("company_id", "=", company.id), ("date", "<=", end),
            ("location_id.usage", "=", "internal"), ("location_dest_id.usage", "=", "customer"),
        ]
        sales = dict(Move._read_group(
            sale_domain + [("date", ">", end - timedelta(days=30))],
            ["product_id"], ["product_qty:sum"],
        ))
        last_sale = dict(Move._read_group(sale_domain, ["product_id"], ["date:max"]))
        first_move = dict(Move._read_group(
            [("product_id", "in", products.ids), ("state", "=", "done"),
             ("company_id", "=", company.id), ("date", "<=", end)],
            ["product_id"], ["date:min"],
        ))
        vals_list = []
        for product in products:
            qty = on_hand.get(product, 0.0)
            sold = sales.get(product, 0.0)
            demand = sold / 30.0
            cost = product.standard_price
            last = last_sale.get(product)
            tmpl = product.product_tmpl_id
            vals_list.append({
                "date": on_date,
                "company_id": company.id,
                "product_id": product.id,
                "product_tmpl_id": tmpl.id,
                "pharma_category": tmpl.pharma_category,
                "laboratory_id": tmpl.pharma_laboratory_id.id,
                "is_generic": tmpl.pharma_generic_type not in (False, "princeps"),
                "quantity": qty,
                "unit_cost": cost,
                "value": qty * cost,
                "sales_30d": sold,
                "daily_demand": demand,
                "coverage_days": qty / demand if demand else (COVERAGE_NONE if qty > 0 else 0.0),
                "qty_expiring_90d": expiring.get(product, 0.0),
                "value_expiring_90d": expiring.get(product, 0.0) * cost,
                "qty_expired": expired.get(product, 0.0),
                "last_sale_date": fields.Date.to_date(last) if last else False,
                # Dormant : en stock depuis plus de 60 jours, sans vente sur cette période.
                "is_dormant": bool(
                    qty > 0 and first_move.get(product)
                    and first_move[product] < end - timedelta(days=60)
                    and (not last or last < end - timedelta(days=60))
                ),
                "is_out_of_stock": qty <= 0,
                "national_shortage": tmpl.pharma_availability_status in ("shortage", "tension"),
            })
        return self.create(vals_list)
