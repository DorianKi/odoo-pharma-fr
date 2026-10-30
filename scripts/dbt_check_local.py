#!/usr/bin/env python3
"""Vérification hors ligne du projet dbt, sans compte Google Cloud.

Charge les CSV produits par export_raw.py dans un PostgreSQL local, traduit chaque modèle
dbt du SQL BigQuery vers PostgreSQL (sqlglot), le crée dans l'ordre des dépendances, puis
exécute les tests déclarés dans les fichiers .yml (unique, not_null, accepted_values,
relationships) et les tests SQL du dossier dbt/tests.

Ce n'est pas un remplaçant de dbt : c'est un filet de sécurité pour la CI et le
développement. En production, `dbt build` tourne sur BigQuery.

    python3 scripts/dbt_check_local.py --export export/ --dbname warehouse_check

Dépendances : psycopg2, jinja2, pyyaml, sqlglot.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

import jinja2
import sqlglot
import yaml

ROOT = Path(__file__).resolve().parent.parent
DBT = ROOT / "dbt"
PG_TYPES = {"INT64": "bigint", "NUMERIC": "numeric", "FLOAT64": "double precision",
            "BOOL": "boolean", "DATE": "date", "TIMESTAMP": "timestamp", "STRING": "text"}

# Fonctions BigQuery sans équivalent direct dans PostgreSQL.
COMPAT = """
CREATE OR REPLACE FUNCTION public.date(ts timestamp, tz text) RETURNS date
    LANGUAGE sql IMMUTABLE AS $$ SELECT (ts AT TIME ZONE 'UTC' AT TIME ZONE tz)::date $$;
CREATE OR REPLACE FUNCTION public.datetime(ts timestamp, tz text) RETURNS timestamp
    LANGUAGE sql IMMUTABLE AS $$ SELECT ts AT TIME ZONE 'UTC' AT TIME ZONE tz $$;
CREATE OR REPLACE FUNCTION public.generate_date_array(a date, b date, step interval)
    RETURNS date[] LANGUAGE sql IMMUTABLE AS
    $$ SELECT array_agg(d::date ORDER BY d) FROM generate_series(a, b, step) d $$;
"""


def load_raw(cur, export_dir):
    cur.execute("DROP SCHEMA IF EXISTS pharma_raw CASCADE; CREATE SCHEMA pharma_raw;")
    for schema_file in sorted(export_dir.glob("*.schema.json")):
        table = schema_file.name.removesuffix(".schema.json")
        columns = json.loads(schema_file.read_text())
        cols = ", ".join(f'"{c["name"]}" {PG_TYPES[c["type"]]}' for c in columns)
        cur.execute(f'CREATE TABLE pharma_raw."{table}" ({cols})')
        with open(export_dir / f"{table}.csv", encoding="utf-8") as handle:
            cur.copy_expert(
                f'COPY pharma_raw."{table}" FROM STDIN WITH (FORMAT csv, HEADER true, NULL \'\')',
                handle)


def discover_models():
    models = {}
    for path in sorted((DBT / "models").rglob("*.sql")):
        layer = path.relative_to(DBT / "models").parts[0]
        models[path.stem] = {"path": path, "layer": layer, "sql": path.read_text()}
    return models


def render(sql, models, project_vars):
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)

    def ref(name):
        return f"pharma_{models[name]['layer']}.{name}"

    def source(_src, table):
        return f'pharma_raw."{table}"'

    return env.from_string(sql).render(
        ref=ref, source=source, var=lambda k, d=None: project_vars.get(k, d),
        config=lambda **kw: "")


def topo_order(models):
    deps = {n: set(re.findall(r"ref\(\s*'([^']+)'\s*\)", m["sql"])) for n, m in models.items()}
    order, seen = [], set()

    def visit(name, stack=()):
        if name in seen:
            return
        if name in stack:
            raise SystemExit(f"Dépendance circulaire : {' → '.join(stack + (name,))}")
        for dep in sorted(deps[name]):
            if dep not in models:
                raise SystemExit(f"{name} : ref('{dep}') inconnu")
            visit(dep, stack + (name,))
        seen.add(name)
        order.append(name)

    for name in sorted(models):
        visit(name)
    return order


# Traductions que sqlglot laisse telles quelles (sémantique BigQuery conservée).
PG_FIXUPS = [
    (r"EXTRACT\(DAYOFWEEK FROM ", "1 + EXTRACT(DOW FROM "),   # BigQuery : 1 = dimanche
    (r"EXTRACT\(ISOWEEK FROM ", "EXTRACT(WEEK FROM "),
    (r"DATE_TRUNC\('ISOWEEK', ", "DATE_TRUNC('WEEK', "),
]


def to_postgres(sql):
    statements = sqlglot.transpile(sql, read="bigquery", write="postgres")
    if len(statements) != 1:
        raise ValueError("un modèle doit contenir une seule requête")
    pg_sql = statements[0]
    for pattern, replacement in PG_FIXUPS:
        pg_sql = re.sub(pattern, replacement, pg_sql)
    return pg_sql


def build(cur, models, project_vars):
    for layer in {m["layer"] for m in models.values()}:
        cur.execute(f"DROP SCHEMA IF EXISTS pharma_{layer} CASCADE; CREATE SCHEMA pharma_{layer};")
    errors = 0
    for name in topo_order(models):
        model = models[name]
        kind = "VIEW" if model["layer"] == "staging" else "TABLE"
        try:
            pg_sql = to_postgres(render(model["sql"], models, project_vars))
            cur.execute("SAVEPOINT m")
            cur.execute(f"CREATE {kind} pharma_{model['layer']}.{name} AS {pg_sql}")
            cur.execute(f"SELECT count(*) FROM pharma_{model['layer']}.{name}")
            print(f"  ok   {model['layer']:8} {name:32} {cur.fetchone()[0]:>8} lignes")
            cur.execute("RELEASE SAVEPOINT m")
        except Exception as exc:  # noqa: BLE001 - on veut voir toutes les erreurs
            cur.execute("ROLLBACK TO SAVEPOINT m")
            errors += 1
            print(f"  ÉCHEC {model['layer']:7} {name}: {str(exc).strip().splitlines()[0]}")
    return errors


def relation(models, name):
    if name in models:
        return f"pharma_{models[name]['layer']}.{name}"
    return f'pharma_raw."{name}"'


def column_tests(models):
    for yml in sorted((DBT / "models").rglob("*.yml")):
        doc = yaml.safe_load(yml.read_text()) or {}
        entries = [(m["name"], m) for m in doc.get("models", [])]
        for src in doc.get("sources", []):
            entries += [(t["name"], t) for t in src.get("tables", [])]
        for table, spec in entries:
            for col in spec.get("columns", []):
                for test in col.get("tests", col.get("data_tests", [])):
                    yield table, col["name"], test


def test_sql(models, table, column, test):
    rel = relation(models, table)
    if test == "unique":
        return (f"SELECT {column} FROM {rel} WHERE {column} IS NOT NULL "
                f"GROUP BY {column} HAVING count(*) > 1")
    if test == "not_null":
        return f"SELECT 1 FROM {rel} WHERE {column} IS NULL"
    if isinstance(test, dict) and "accepted_values" in test:
        values = ", ".join(f"'{v}'" for v in test["accepted_values"]["values"])
        return f"SELECT {column} FROM {rel} WHERE {column} NOT IN ({values})"
    if isinstance(test, dict) and "relationships" in test:
        spec = test["relationships"]
        target = re.search(r"ref\('([^']+)'\)", spec["to"]).group(1)
        return (f"SELECT {column} FROM {rel} WHERE {column} IS NOT NULL AND {column} NOT IN "
                f"(SELECT {spec['field']} FROM {relation(models, target)})")
    return None


def run_tests(cur, models, project_vars):
    failures = 0
    checks = [(f"{t}.{c} {k if isinstance(k, str) else next(iter(k))}", test_sql(models, t, c, k))
              for t, c, k in column_tests(models)]
    for path in sorted((DBT / "tests").glob("*.sql")):
        checks.append((path.stem, to_postgres(render(path.read_text(), models, project_vars))))
    for label, sql in checks:
        if sql is None:
            print(f"  ?    {label} (test non géré ici)")
            continue
        cur.execute("SAVEPOINT t")
        try:
            cur.execute(f"SELECT count(*) FROM ({sql}) AS t")
            bad = cur.fetchone()[0]
            cur.execute("RELEASE SAVEPOINT t")
        except Exception as exc:  # noqa: BLE001
            cur.execute("ROLLBACK TO SAVEPOINT t")
            bad = f"erreur : {str(exc).strip().splitlines()[0]}"
        if bad:
            failures += 1
            print(f"  ÉCHEC {label} : {bad}")
    print(f"  {len(checks) - failures}/{len(checks)} tests réussis")
    return failures


def parse_only(project_vars):
    models = discover_models()
    topo_order(models)
    errors = 0
    for name, model in sorted(models.items()):
        try:
            sqlglot.parse_one(render(model["sql"], models, project_vars), read="bigquery")
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"ÉCHEC {name}: {exc}")
    print(f"{len(models) - errors}/{len(models)} modèles analysés sans erreur")
    return 1 if errors else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--export", default="export")
    parser.add_argument("--dbname", default="warehouse_check")
    parser.add_argument("--host", default=os.environ.get("PGHOST", "localhost"))
    parser.add_argument("--port", default=os.environ.get("PGPORT", "5432"))
    parser.add_argument("--user", default=os.environ.get("PGUSER", "odoo"))
    parser.add_argument("--parse-only", action="store_true",
                        help="vérifie seulement que chaque modèle est du SQL BigQuery valide")
    args = parser.parse_args()

    project = yaml.safe_load((DBT / "dbt_project.yml").read_text())
    project_vars = project.get("vars", {})
    if args.parse_only:
        return parse_only(project_vars)

    import psycopg2
    conn = psycopg2.connect(dbname=args.dbname, host=args.host, port=args.port, user=args.user,
                            password=os.environ.get("PGPASSWORD", "odoo"))
    models = discover_models()
    with conn, conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'UTC'")
        cur.execute(COMPAT)
        load_raw(cur, Path(args.export))
        print("Modèles :")
        errors = build(cur, models, project_vars)
        print("Tests :")
        failures = run_tests(cur, models, project_vars)
    conn.close()
    return 1 if errors or failures else 0


if __name__ == "__main__":
    sys.exit(main())
