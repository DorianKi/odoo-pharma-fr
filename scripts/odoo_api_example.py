"""Interroger Odoo par son API (XML-RPC), sans passer par SQL.

    python scripts/odoo_api_example.py

L'API respecte les droits d'accès et renvoie les champs calculés : c'est la voie à
privilégier pour alimenter un outil externe (cloud, tableau de bord).
"""

import xmlrpc.client

URL, DB, USER, PASSWORD = "http://localhost:8069", "pharmacie", "admin", "admin"

uid = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common").authenticate(DB, USER, PASSWORD, {})
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")


def search_read(model, domain, fields, **kwargs):
    return models.execute_kw(DB, uid, PASSWORD, model, "search_read", [domain],
                             {"fields": fields, **kwargs})


# Ordonnances délivrées : montants et marge
for rx in search_read("pharma.prescription", [("state", "=", "done")],
                      ["name", "dispensing_date", "amount_total", "margin"], limit=10):
    print(rx)

# Articles en rupture nationale
print(search_read("product.template", [("pharma_availability_status", "in", ["shortage", "tension"])],
                  ["name", "barcode", "pharma_availability_status"]))
