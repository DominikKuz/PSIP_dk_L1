r"""PSIP: normalizacja BDOT10k i ocena przejezdnosci na H3.

Uruchom w katalogu projektu (PowerShell):
    .\.venv\Scripts\python.exe .\app\normalizuj_przejezdnosc.py --resolution 7

Wymaga: psycopg2, geopandas, matplotlib, numpy. Baza: env-test (localhost:5434).
Wagi: plik wagi_przejezdnosci.json w tym samym katalogu co skrypt.

WAZNE: Model demonstracyjny dla pojazdu terenowego, nie mapa rzeczywistej
bezpiecznej przejezdnosci. Brak danych o nachyleniu, nosnosci, wilgotnosci,
przeszkodach i szerokosci drogi. Wagi wymagaja zatwierdzenia.
"""
import argparse
import json
from getpass import getpass
from pathlib import Path

import psycopg2
from psycopg2 import sql


def ident(name):
    return sql.Identifier(name)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--resolution', type=int, choices=[7, 8, 9], required=True)
    p.add_argument('--no-map', action='store_true', help='Pomin tworzenie PNG')
    args = p.parse_args()
    weights_file = Path(__file__).with_name('wagi_przejezdnosci.json')
    weights = json.loads(weights_file.read_text(encoding='utf-8'))
    if not weights or any(not isinstance(v, (int, float)) or not -1 <= v <= 1 for v in weights.values()):
        raise ValueError('Wagi musza byc liczbami z przedzialu [-1,1]')

    source = f'h3_aggregation_r{args.resolution}'
    output = f'h3_przejezdnosc_r{args.resolution}'
    password = getpass('Haslo PostgreSQL env-test (nie bedzie widoczne): ')
    conn_info = dict(host='localhost', port=5434, dbname='psip', user='psip', password=password)
    del password
    conn = psycopg2.connect(**conn_info)
    try:
        with conn.cursor() as cur:
            cur.execute('''SELECT column_name FROM information_schema.columns
                           WHERE table_schema='grid' AND table_name=%s''', (source,))
            available = {r[0] for r in cur.fetchall()}
            if not available:
                raise RuntimeError(f'Nie znaleziono grid.{source}')
            missing = set(weights) - available
            extra = {x for x in available if x.endswith(('_m2','_m','_count'))} - set(weights)
            if missing or extra:
                raise RuntimeError(f'Niezgodnosc kolumn: brak={sorted(missing)}; bez wagi={sorted(extra)}')
            if not {'geometry','h3_id'} <= available:
                raise RuntimeError('Brak wymaganych kolumn geometry/h3_id')
            cur.execute(sql.SQL('SELECT MIN(ST_SRID(geometry)), MAX(ST_SRID(geometry)), COUNT(*) FROM grid.{}').format(ident(source)))
            low,high,count=cur.fetchone()
            if low != 4326 or high != 4326 or count == 0:
                raise RuntimeError(f'Oczekiwano EPSG:4326 i >0 wierszy, jest {low}..{high} ({count})')

            names = list(weights)
            maxima = sql.SQL(', ').join(sql.SQL('MAX(COALESCE({},0))::double precision AS {}').format(ident(c), ident('max_'+c)) for c in names)
            expressions = []
            terms = []
            for c in names:
                norm = sql.SQL('(CASE WHEN m.{} > 0 THEN COALESCE(h.{},0)::double precision / m.{} ELSE 0.0 END)').format(ident('max_'+c),ident(c),ident('max_'+c))
                expressions.append(sql.SQL('{} AS {}').format(norm, ident(c+'_norm')))
                terms.append(sql.SQL('({} * {})').format(norm,sql.Literal(float(weights[c]))))
            score = sql.SQL('({}) / {}').format(sql.SQL(' + ').join(terms),sql.Literal(len(names)))
            query = sql.SQL('''CREATE TABLE grid.{} AS
               WITH maxima AS (SELECT {} FROM grid.{})
               SELECT h.*, {}, {}::double precision AS wsp_iop_norm
               FROM grid.{} h CROSS JOIN maxima m''').format(
                    ident(output),maxima,ident(source),sql.SQL(', ').join(expressions),score,ident(source))
            cur.execute(sql.SQL('DROP TABLE IF EXISTS grid.{}').format(ident(output)))
            cur.execute(query)
            cur.execute(sql.SQL('ALTER TABLE grid.{} ADD PRIMARY KEY (h3_id)').format(ident(output)))
            cur.execute(sql.SQL('CREATE INDEX ON grid.{} USING gist(geometry)').format(ident(output)))
            cur.execute(sql.SQL('''SELECT COUNT(*), MIN(wsp_iop_norm), MAX(wsp_iop_norm)
                                   FROM grid.{}''').format(ident(output)))
            n,vmin,vmax=cur.fetchone()
            if vmin < -1.00000001 or vmax > 1.00000001:
                raise ValueError('Wynik poza [-1,1]')
            print(f'GOTOWE: grid.{output}, {n} heksagonow, zakres [{vmin:.5f}, {vmax:.5f}]')
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if not args.no_map:
        import geopandas as gpd
        import matplotlib.pyplot as plt
        from matplotlib.colors import ListedColormap, BoundaryNorm
        from matplotlib.patches import Patch
        from sqlalchemy import create_engine
        from sqlalchemy.engine import URL
        engine = create_engine(URL.create('postgresql+psycopg2',username='psip',password=conn_info['password'],host='localhost',port=5434,database='psip'))
        try:
            gdf = gpd.read_postgis(f'SELECT h3_id, wsp_iop_norm, geometry FROM grid.{output}',engine,geom_col='geometry')
        finally:
            engine.dispose()
        cmap = ListedColormap(['#c63131', '#ffffff', '#238b45'])

        minimum = float(gdf['wsp_iop_norm'].min())
        maksimum = float(gdf['wsp_iop_norm'].max())

        krok = (maksimum - minimum) / 3

        granica1 = minimum + krok
        granica2 = minimum + 2 * krok

        norm = BoundaryNorm(
            [minimum, granica1, granica2, maksimum + 0.000001],
            cmap.N
        )
        fig,ax=plt.subplots(figsize=(10,10))
        gdf.plot(column='wsp_iop_norm',ax=ax,cmap=cmap,norm=norm,linewidth=0.12,edgecolor='#555555')
        ax.set_title(f'Przejezdnosc terenu — H3 r{args.resolution}\nWspolczynnik od -1 do 1',fontsize=14)
        ax.set_axis_off()
        ax.legend(
            handles=[
                Patch(facecolor='#c63131', label=f'{minimum:.4f} do {granica1:.4f} – trudny'),
                Patch(facecolor='#ffffff', edgecolor='black',
                      label=f'{granica1:.4f} do {granica2:.4f} – średni'),
                Patch(facecolor='#238b45', label=f'{granica2:.4f} do {maksimum:.4f} – przejezdny')
            ],
            loc='lower left'
        )
        fig.tight_layout()
        out = Path(__file__).resolve().parent.parent / 'wyniki' / f'przejezdnosc_r{args.resolution}.png'
        out.parent.mkdir(exist_ok=True)
        fig.savefig(out,dpi=220,bbox_inches='tight')
        plt.close(fig)
        print('MAPA:',out)

if __name__=='__main__':
    main()
