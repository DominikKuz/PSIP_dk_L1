
from pathlib import Path
from getpass import getpass
import re

import geopandas as gpd
import pandas as pd
import pyogrio

from shapely.geometry import (
    Polygon, MultiPolygon,
    LineString, MultiLineString,
    Point, MultiPoint
)

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


# LOKALIZACJE DANYCH
DATA = Path(__file__).resolve().parent.parent / "data"

POWIAT = DATA / "PL.PZGIK.994.0415_BDOT10k.gpkg"
MIASTO = DATA / "BDOT_Torun_miasto"

# POSTGIS ENV-TEST
DB_USER = "psip"
DB_NAME = "psip"
DB_PORT = 5434


def wczytaj_geometrie(plik, warstwa=None, zrodlo=""):
    dane = gpd.read_file(
        plik,
        layer=warstwa,
        columns=[]
    )

    if dane.crs is None:
        raise ValueError(f"Brak CRS: {plik}")

    dane = dane.to_crs(epsg=2180)
    dane = dane[["geometry"]].copy()
    dane = dane[
        dane.geometry.notna() & ~dane.geometry.is_empty
    ].copy()

    dane["zrodlo"] = zrodlo

    return dane


def ujednolic_geometrie(geom):
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    if isinstance(geom, LineString):
        return MultiLineString([geom])
    if isinstance(geom, Point):
        return MultiPoint([geom])
    return geom


def main():
    if not POWIAT.exists():
        raise FileNotFoundError(POWIAT)

    if not MIASTO.is_dir():
        raise FileNotFoundError(MIASTO)

    # Klasy BDOT10k powiatu 0415
    klasy_powiatu = {
        nazwa
        for nazwa, typ in pyogrio.list_layers(POWIAT)
        if typ is not None
    }

    # Klasy BDOT10k miasta 0463
    klasy_miasta = {}

    for plik in MIASTO.rglob("*.gpkg"):
        wynik = re.search(
            r"(OT_[A-Z0-9]+_[ALP])$",
            plik.stem.upper()
        )

        if wynik:
            klasa = wynik.group(1)

            if klasa in klasy_miasta:
                raise ValueError(
                    f"Powtorzona klasa miasta: {klasa}"
                )

            klasy_miasta[klasa] = plik

    wszystkie_klasy = sorted(
        klasy_powiatu | set(klasy_miasta)
    )

    if len(klasy_powiatu) != 69 or len(klasy_miasta) != 68:
        raise RuntimeError(
            "Nieoczekiwana liczba klas BDOT10k. "
            f"Powiat: {len(klasy_powiatu)}, "
            f"miasto: {len(klasy_miasta)}"
        )

    if len(wszystkie_klasy) != 70:
        raise RuntimeError(
            f"Oczekiwano 70 klas, znaleziono "
            f"{len(wszystkie_klasy)}"
        )

    print("Powiat torunski:", len(klasy_powiatu))
    print("Miasto Torun:", len(klasy_miasta))
    print("Lacznie klas:", len(wszystkie_klasy))

    haslo = getpass("Haslo bazy env-test: ")

    engine = create_engine(
        URL.create(
            "postgresql+psycopg2",
            username=DB_USER,
            password=haslo,
            host="127.0.0.1",
            port=DB_PORT,
            database=DB_NAME,
        )
    )

    try:
        with engine.begin() as conn:
            conn.execute(
                text("CREATE SCHEMA IF NOT EXISTS bdot")
            )

        for i, klasa in enumerate(wszystkie_klasy, 1):
            fragmenty = []

            if klasa in klasy_powiatu:
                fragmenty.append(
                    wczytaj_geometrie(
                        POWIAT,
                        warstwa=klasa,
                        zrodlo="0415"
                    )
                )

            if klasa in klasy_miasta:
                fragmenty.append(
                    wczytaj_geometrie(
                        klasy_miasta[klasa],
                        zrodlo="0463"
                    )
                )

            dane = gpd.GeoDataFrame(
                pd.concat(
                    fragmenty,
                    ignore_index=True
                ),
                geometry="geometry",
                crs="EPSG:2180"
            )

            dane = dane[
                dane.geometry.notna()
                & ~dane.geometry.is_empty
            ].copy()

            if dane.empty:
                print(f"Pominieto pusta klase: {klasa}")
                continue

            dane["geometry"] = dane.geometry.apply(
                ujednolic_geometrie
            )

            tabela = klasa.lower()

            # Zastepujemy stara tabele polaczonymi danymi
            dane.to_postgis(
                tabela,
                engine,
                schema="bdot",
                if_exists="replace",
                index=False,
                chunksize=1000
            )

            print(
                f"[{i}/{len(wszystkie_klasy)}] "
                f"{tabela}: {len(dane)} obiektow",
                flush=True
            )

        print()
        print("GOTOWE - BDOT10k polaczone!")
        print("Obszar: powiat torunski + miasto Torun")
        print("Baza: env-test")
        print("Schemat: bdot")

    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
