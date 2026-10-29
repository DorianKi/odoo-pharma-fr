import math
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class PharmaReplenishmentWizard(models.TransientModel):
    """Calcule les seuils mini / maxi de réassort à partir des ventes réelles.

    Pour chaque article :

    * consommation moyenne journalière = sorties vers les clients sur la période
      d'historique / nombre de jours ;
    * stock mini = consommation × (délai fournisseur + stock de sécurité) ;
    * stock maxi = stock mini + consommation × couverture visée.

    Les règles de réapprovisionnement Odoo (déclenchement automatique, route
    « Acheter ») sont créées ou mises à jour en conséquence.
    """

    _name = "pharma.replenishment.wizard"
    _description = "Calcul des seuils de réassort"

    warehouse_id = fields.Many2one(
        "stock.warehouse", required=True,
        default=lambda self: self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        ),
    )
    product_tmpl_ids = fields.Many2many(
        "product.template", string="Articles",
        help="Laisser vide pour traiter tous les articles officine stockables.",
    )
    history_days = fields.Integer("Historique analysé (jours)", default=90, required=True)
    coverage_days = fields.Integer("Couverture visée (jours)", default=7, required=True)
    safety_days = fields.Integer("Stock de sécurité (jours)", default=2, required=True)
    default_lead_days = fields.Integer(
        "Délai fournisseur par défaut (jours)", default=1, required=True,
        help="Utilisé quand l'article n'a pas de délai fournisseur renseigné.",
    )
    deactivate_dormant = fields.Boolean(
        "Mettre à zéro les articles sans vente",
        help="Les règles existantes des articles sans vente sur la période sont "
             "ramenées à 0 / 0 (pas de réassort automatique des produits dormants).",
    )
    result = fields.Text(readonly=True)
    state = fields.Selection([("draft", "Paramètres"), ("done", "Terminé")], default="draft")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if self.env.context.get("active_model") == "product.template":
            values["product_tmpl_ids"] = [
                fields.Command.set(self.env.context.get("active_ids", []))
            ]
        return values

    def _get_products(self):
        if self.product_tmpl_ids:
            templates = self.product_tmpl_ids
        else:
            templates = self.env["product.template"].search([
                ("pharma_category", "!=", False),
                ("is_storable", "=", True),
            ])
        return templates.filtered("is_storable").product_variant_ids

    def _get_consumption(self, products):
        """Quantités sorties vers les clients sur la période, par article."""
        date_from = fields.Datetime.now() - timedelta(days=self.history_days)
        data = self.env["stock.move"]._read_group(
            [
                ("product_id", "in", products.ids),
                ("state", "=", "done"),
                ("date", ">=", date_from),
                ("location_id.usage", "=", "internal"),
                ("location_dest_id.usage", "=", "customer"),
                ("location_id.warehouse_id", "=", self.warehouse_id.id),
            ],
            ["product_id"],
            ["product_qty:sum"],
        )
        return {product.id: qty for product, qty in data}

    def _get_lead_days(self, product):
        seller = product._select_seller(quantity=None)
        return seller.delay if seller and seller.delay else self.default_lead_days

    @api.model
    def _compute_thresholds(self, daily, lead_days, safety_days, coverage_days):
        """(mini, maxi) arrondis à l'unité supérieure ; (0, 0) sans consommation."""
        if daily <= 0:
            return 0, 0
        minimum = math.ceil(daily * (lead_days + safety_days))
        maximum = math.ceil(daily * (lead_days + safety_days + coverage_days))
        return minimum, max(maximum, minimum + 1)

    def action_compute(self):
        self.ensure_one()
        if min(self.history_days, self.coverage_days) <= 0 or self.safety_days < 0:
            raise UserError("Les durées doivent être positives.")
        products = self._get_products()
        if not products:
            raise UserError("Aucun article stockable à traiter.")
        consumption = self._get_consumption(products)
        Orderpoint = self.env["stock.warehouse.orderpoint"]
        location = self.warehouse_id.lot_stock_id
        existing = {
            op.product_id.id: op
            for op in Orderpoint.with_context(active_test=False).search([
                ("product_id", "in", products.ids),
                ("location_id", "=", location.id),
            ])
        }
        buy_route = self.env.ref("purchase_stock.route_warehouse0_buy", raise_if_not_found=False)
        created = updated = dormant = 0
        to_create = []
        for product in products:
            daily = consumption.get(product.id, 0.0) / self.history_days
            orderpoint = existing.get(product.id)
            if daily <= 0:
                dormant += 1
                if orderpoint and self.deactivate_dormant:
                    orderpoint.write({"product_min_qty": 0, "product_max_qty": 0})
                    updated += 1
                continue
            minimum, maximum = self._compute_thresholds(
                daily, self._get_lead_days(product), self.safety_days, self.coverage_days
            )
            values = {"product_min_qty": minimum, "product_max_qty": maximum, "trigger": "auto"}
            if orderpoint:
                orderpoint.write(dict(values, active=True))
                updated += 1
            else:
                values.update({
                    "product_id": product.id,
                    "warehouse_id": self.warehouse_id.id,
                    "location_id": location.id,
                    "route_id": buy_route.id if buy_route else False,
                })
                to_create.append(values)
        if to_create:
            Orderpoint.create(to_create)
            created = len(to_create)
        self.write({
            "state": "done",
            "result": (
                f"Articles analysés : {len(products)}\n"
                f"Règles créées : {created}\n"
                f"Règles mises à jour : {updated}\n"
                f"Articles sans vente sur {self.history_days} jours : {dormant}"
            ),
        })
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_open_orderpoints(self):
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "stock.action_orderpoint"
        )
        action["domain"] = [("warehouse_id", "=", self.warehouse_id.id)]
        action["context"] = {}
        return action
