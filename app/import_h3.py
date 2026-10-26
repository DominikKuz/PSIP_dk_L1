
import os
import geopandas as gpd
from sqlalchemy import create_engine, text
from geoalchemy2 import Geometry

gpkg = r"D:\Projekty\PSIP_dk_L1\data\hexagons.gpkg"

from getpass import getpass
from sqlalchemy.engine import URL

databases = {
    "env-test": ("psip", "psip", 5434),
    "env-qa": ("psip-qa", "psip-qa", 5435),
    "main": ("psip-main", "psip-main", 5436),
}

environment = input("Podaj środowisko (env-test/env-qa/main): ").strip()

if environment not in databases:
    raise ValueError("Nieznane środowisko")

user, dbname, port = databases[environment]
password = getpass("Hasło PostgreSQL: ")

engine = create_engine(
    URL.create(
        "postgresql+psycopg2",
        username=user,
        password=password,
        host="localhost",
        port=port,
        database=dbname,
    )
)
with engine.begin() as conn:
    conn.execute(text("CREATE SCHEMA IF NOT EXISTS grid"))

for resolution in (7, 8, 9):
    layer = f"h3_r{resolution}"
    print(f"Importowanie: {layer}")

    gdf = gpd.read_file(gpkg, layer=layer)

    if gdf.crs is None:
        raise ValueError(f"Brak układu współrzędnych: {layer}")

    gdf = gdf.to_crs(epsg=4326)

    gdf.to_postgis(
        layer,
        engine,
        schema="grid",
        if_exists="replace",
        index=False,
        dtype={"geometry": Geometry("POLYGON", srid=4326)},
    )

    print(f"Zapisano {len(gdf)} heksagonów")

engine.dispose()
print("Import zakończony!")
