
from pathlib import Path
from getpass import getpass

import geopandas as gpd
import pyogrio
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# Plik BDOT10k powiatu toruńskiego
GPKG = Path(__file__).resolve().parent.parent / "data" / "PL.PZGIK.994.0415_BDOT10k.gpkg"

# Baza testowa PostGIS
DB_USER = "psip"
DB_NAME = "psip"
DB_PORT = 5434

if not GPKG.exists():
    raise FileNotFoundError(f"Nie znaleziono pliku: {GPKG}")

password = getpass("Hasło bazy env-test: ")

engine = create_engine(
    URL.create(
        "postgresql+psycopg2",
        username=DB_USER,
        password=password,
        host="localhost",
        port=DB_PORT,
        database=DB_NAME,
    )
)

try:
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS bdot"))

    layers = pyogrio.list_layers(GPKG)

    for name, geometry_type in layers:
        if geometry_type is None:
            continue

        print(f"\nImport warstwy: {name}")

        gdf = gpd.read_file(GPKG, layer=name)

        if gdf.empty:
            print("Pusta warstwa - pomijam")
            continue

        if gdf.crs is None:
            raise ValueError(f"Brak CRS w warstwie {name}")

        # Układ metryczny do obliczeń powierzchni i długości
        gdf = gdf.to_crs(epsg=2180)

        # Nazwy tabel bez wielkich liter
        table_name = name.lower()

        gdf.to_postgis(
            table_name,
            engine,
            schema="bdot",
            if_exists="replace",
            index=False,
            chunksize=1000,
        )

        print(f"Zaimportowano {len(gdf)} obiektów")

    print("\nImport BDOT10k zakończony!")

finally:
    engine.dispose()
