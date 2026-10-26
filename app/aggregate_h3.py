"""Agregacja BDOT10k do H3 w bazie env-test (powiat torunski).

Uruchom z katalogu projektu:
  .\.venv\Scripts\python.exe .\app\aggregate_h3.py --resolution 7 --limit-layers 3
  .\.venv\Scripts\python.exe .\app\aggregate_h3.py --resolution 7
  .\.venv\Scripts\python.exe .\app\aggregate_h3.py --resolution 8
  .\.venv\Scripts\python.exe .\app\aggregate_h3.py --resolution 9

Dane: grid.h3_r7/r8/r9 (EPSG:4326), bdot.* (EPSG:2180).
Wyniki: grid.h3_aggregation_r7/r8/r9 (EPSG:2180) z osobnymi kolumnami
warstw BDOT. Test --limit-layers N tworzy osobna tabele ..._test.
"""
import argparse
from getpass import getpass
import os

import psycopg2
from psycopg2 import sql


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--resolution', type=int, choices=[7, 8, 9], default=7)
    parser.add_argument('--limit-layers', type=int, default=None,
                        help='Test: przetworz tylko N warstw i zapisz do osobnej tabeli _test')
    args = parser.parse_args()
    if args.limit_layers is not None and args.limit_layers < 1:
        parser.error('--limit-layers musi byc dodatnie')

    passwd = os.environ.get('POSTGRES_PASSWORD') or getpass('Haslo bazy env-test: ')
    conn = psycopg2.connect(host='127.0.0.1', port=5434, dbname='psip',
                            user='psip', password=passwd, connect_timeout=15)
    conn.autocommit = False
    source = f'h3_r{args.resolution}'
    out = f'h3_aggregation_r{args.resolution}' + ('_test' if args.limit_layers else '')

    try:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT f_table_name, f_geometry_column, type, srid
                FROM geometry_columns WHERE f_table_schema='bdot'
                ORDER BY f_table_name
            ''')
            layers = cur.fetchall()
            if not layers:
                raise RuntimeError('Brak tabel geometrycznych w schemacie bdot')
            if args.limit_layers:
                layers = layers[:args.limit_layers]
            for table, geom, typ, srid in layers:
                if srid != 2180:
                    raise RuntimeError(f'bdot.{table}: oczekiwano EPSG:2180, jest {srid}')

            cur.execute(sql.SQL('SELECT COUNT(*), COUNT(DISTINCT h3_id), MIN(ST_SRID(geometry)) FROM grid.{}').format(sql.Identifier(source)))
            n, distinct, srid = cur.fetchone()
            if n == 0 or n != distinct or srid != 4326:
                raise RuntimeError(f'{source}: nieprawidlowe dane H3: {n=} {distinct=} {srid=}')

            # Budujemy wynik w nowej tabeli, nie nadpisujac siatek zrodlowych.
            cur.execute(sql.SQL('DROP TABLE IF EXISTS grid.{}').format(sql.Identifier(out)))
            cur.execute(sql.SQL('''
                CREATE TABLE grid.{} AS
                SELECT h3_id, resolution,
                       ST_Transform(geometry, 2180)::geometry(Polygon,2180) AS geometry
                FROM grid.{}
            ''').format(sql.Identifier(out), sql.Identifier(source)))
            cur.execute(sql.SQL('ALTER TABLE grid.{} ADD PRIMARY KEY (h3_id)').format(sql.Identifier(out)))
            cur.execute(sql.SQL('CREATE INDEX ON grid.{} USING gist (geometry)').format(sql.Identifier(out)))
            conn.commit()

        print(f'Siatka: {source} ({n} heksagonow); BDOT: {len(layers)} warstw', flush=True)
        for i, (table, geom, geom_type, _) in enumerate(layers, 1):
            kind = geom_type.upper()
            if 'POLYGON' in kind:
                suffix, db_type = 'm2', sql.SQL('double precision')
                value = sql.SQL('COALESCE(SUM(ST_Area(ST_Intersection(h.geometry, b.{geom}))),0)').format(geom=sql.Identifier(geom))
                spatial_predicate = sql.SQL('ST_Intersects(h.geometry, b.{geom})').format(geom=sql.Identifier(geom))
            elif 'LINESTRING' in kind:
                suffix, db_type = 'm', sql.SQL('double precision')
                value = sql.SQL('COALESCE(SUM(ST_Length(ST_Intersection(h.geometry, b.{geom}))),0)').format(geom=sql.Identifier(geom))
                spatial_predicate = sql.SQL('ST_Intersects(h.geometry, b.{geom})').format(geom=sql.Identifier(geom))
            elif 'POINT' in kind:
                suffix, db_type = 'count', sql.SQL('bigint')
                value = sql.SQL('COUNT(*)')
                # ST_Contains nie liczy punktow na krawedziach dwoch komorek.
                # Punkty dokladnie na granicy zostana pominiete (sprawdzic w kontroli QA).
                spatial_predicate = sql.SQL('ST_Contains(h.geometry, b.{geom})').format(geom=sql.Identifier(geom))
            else:
                print(f'Pominieto nieobslugiwany typ {table}: {kind}', flush=True)
                continue

            column = f'{table}_{suffix}'
            with conn.cursor() as cur:
                # Indeks przestrzenny przyspiesza zapytania; istnieje takze po ponownym uruchomieniu.
                idx_name = f'idx_{table}_{geom}_gist'
                cur.execute(sql.SQL('CREATE INDEX IF NOT EXISTS {} ON bdot.{} USING gist ({})').format(
                    sql.Identifier(idx_name), sql.Identifier(table), sql.Identifier(geom)))
                cur.execute(sql.SQL('ALTER TABLE grid.{} ADD COLUMN {} {} DEFAULT 0').format(
                    sql.Identifier(out), sql.Identifier(column), db_type))
                cur.execute(sql.SQL('''
                    UPDATE grid.{} AS h SET {} = (
                        SELECT {} FROM bdot.{} b
                        WHERE b.{} IS NOT NULL AND {}
                    )
                ''').format(sql.Identifier(out), sql.Identifier(column), value,
                            sql.Identifier(table), sql.Identifier(geom), spatial_predicate))
                conn.commit()
            print(f'[{i}/{len(layers)}] {table} -> {column}', flush=True)
        with conn.cursor() as cur:
            cur.execute(sql.SQL('ANALYZE grid.{}').format(sql.Identifier(out)))
            conn.commit()
        print(f'GOTOWE: grid.{out} | {n} heksagonow', flush=True)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
