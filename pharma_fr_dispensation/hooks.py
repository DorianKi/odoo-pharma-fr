def post_init_hook(env):
    """Paramètres de l'officine à l'installation : stratégie de sortie FEFO
    (premier périmé, premier sorti) sur les stocks, TVA des honoraires."""
    fefo = env.ref("product_expiry.removal_fefo", raise_if_not_found=False)
    if fefo:
        env["stock.warehouse"].search([]).lot_stock_id.removal_strategy_id = fefo
    for company in env["res.company"].search([]):
        env["product.template"].with_company(company)._pharma_ensure_fee_taxes()
