"""Końcowa normalizacja istniejących wyników IOP na env-test.

Nie przelicza BDOT10k ani wag. Używa wspólnego minimum i maksimum
surowych wyników r7, r8 i r9, aby zachować porównywalność siatek.
"""

import getpass
import os
import sys

import psycopg2
from psycopg2 import sql

SCHEMA = "grid"
TABLES = ["h3_przejezdnosc_r7", "h3_przejezdnosc_r8", "h3_przejezdnosc_r9"]


def table_id(name):
    return sql.Identifier(SCHEMA, name)


def main():
    print("Końcowa normalizacja IOP na bazie env-test (port 5434).")
    print("Źródłem są istniejące wyniki. BDOT10k i wagi nie są przeliczane.")
    password = os.environ.get("PSIP_DB_PASSWORD") or getpass.getpass("Hasło do bazy env-test (psip): ")
    conn = psycopg2.connect(host="127.0.0.1", port=5434, dbname="psip", user="psip", password=password)
    try:
        with conn:
            with conn.cursor() as cur:
                for name in TABLES:
                    cur.execute("SELECT to_regclass(%s)", (f"{SCHEMA}.{name}",))
                    if cur.fetchone()[0] is None:
                        raise RuntimeError(f"Brakuje tabeli {SCHEMA}.{name}")
                    cur.execute("""
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema=%s AND table_name=%s
                        AND column_name IN ('wsp_iop_norm','wsp_iop_surowy')
                    """, (SCHEMA, name))
                    cols = {r[0] for r in cur.fetchall()}
                    if "wsp_iop_norm" not in cols:
                        raise RuntimeError(f"Brak kolumny wsp_iop_norm: {SCHEMA}.{name}")
                    if "wsp_iop_surowy" not in cols:
                        cur.execute(sql.SQL(
                            "ALTER TABLE {} ADD COLUMN wsp_iop_surowy double precision"
                        ).format(table_id(name)))
                        cur.execute(sql.SQL(
                            "UPDATE {} SET wsp_iop_surowy = wsp_iop_norm"
                        ).format(table_id(name)))
                    else:
                        # Przy ponownym uruchomieniu zachowaj oryginały, nie kopiuj już znormalizowanych wartości.
                        cur.execute(sql.SQL(
                            "UPDATE {} SET wsp_iop_surowy = wsp_iop_norm WHERE wsp_iop_surowy IS NULL AND wsp_iop_norm IS NOT NULL"
                        ).format(table_id(name)))
                    cur.execute(sql.SQL(
                        "ALTER TABLE {} ADD COLUMN IF NOT EXISTS klasa_przejezdnosci integer"
                    ).format(table_id(name)))

                parts = [sql.SQL("SELECT wsp_iop_surowy AS value FROM {}").format(table_id(n)) for n in TABLES]
                cur.execute(sql.SQL("SELECT MIN(value), MAX(value) FROM ({}) x").format(sql.SQL(" UNION ALL ").join(parts)))
                minimum, maximum = cur.fetchone()
                if minimum is None or maximum is None:
                    raise RuntimeError("Brak surowych wyników IOP w tabelach")
                print(f"Wspólne minimum surowe: {minimum:.8f}")
                print(f"Wspólne maksimum surowe: {maximum:.8f}")

                for name in TABLES:
                    if maximum > minimum:
                        cur.execute(sql.SQL("""
                            UPDATE {}
                            SET wsp_iop_norm = CASE
                                    WHEN wsp_iop_surowy IS NULL THEN NULL
                                    ELSE GREATEST(-1.0, LEAST(1.0,
                                        2.0 * (wsp_iop_surowy - %s) / (%s - %s) - 1.0
                                    ))
                                END
                        """).format(table_id(name)), (minimum, maximum, minimum))
                    else:
                        # Przy identycznych wynikach brak zróżnicowania, więc wartość neutralna.
                        cur.execute(sql.SQL("UPDATE {} SET wsp_iop_norm = CASE WHEN wsp_iop_surowy IS NULL THEN NULL ELSE 0.0 END").format(table_id(name)))
                    cur.execute(sql.SQL("""
                        UPDATE {} SET klasa_przejezdnosci = CASE
                            WHEN wsp_iop_norm IS NULL THEN NULL
                            WHEN wsp_iop_norm < -1.0/3.0 THEN 1
                            WHEN wsp_iop_norm <= 1.0/3.0 THEN 2
                            ELSE 3
                        END
                    """).format(table_id(name)))
                    cur.execute(sql.SQL("""
                        SELECT COUNT(*), MIN(wsp_iop_norm), MAX(wsp_iop_norm),
                               COUNT(*) FILTER (WHERE klasa_przejezdnosci=1),
                               COUNT(*) FILTER (WHERE klasa_przejezdnosci=2),
                               COUNT(*) FILTER (WHERE klasa_przejezdnosci=3)
                        FROM {}
                    """).format(table_id(name)))
                    count, mi, ma, c1, c2, c3 = cur.fetchone()
                    print(f"{name}: {count} heks.; zakres {mi:.5f} do {ma:.5f}; czerwone={c1}, białe={c2}, zielone={c3}")
        print("GOTOWE. Wyniki zapisane w PostGIS. Wyświetl w QGIS kolumnę klasa_przejezdnosci.")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        sys.exit(1)
