"""Generator siatek H3 (7, 8, 9) dla granicy powiatu.
Uruchom wewnątrz kontenera Python z geopandas, shapely, h3, pyogrio/fiona.
Wynik: plik GeoPackage z warstwami h3_r7, h3_r8, h3_r9.
"""
import os
from pathlib import Path

import geopandas as gpd
import h3
from shapely.geometry import Polygon, mapping
from shapely.ops import unary_union

RESOLUTIONS = (7, 8, 9)
OUTPUT = Path(os.getenv("H3_OUTPUT", "/app/hexagons.gpkg"))


def input_path():
    defined = os.getenv("H3_INPUT")
    if defined:
        path = Path(defined)
        if not path.exists():
            raise FileNotFoundError(f"H3_INPUT nie istnieje: {path}")
        return path
    for directory in (Path("/app/data"), Path("/data")):
        for path in sorted(directory.glob("powiat*.shp")):
            return path
    raise FileNotFoundError("Brak powiat*.shp w /app/data lub /data. Ustaw H3_INPUT.")


def main():
    source = input_path()
    boundaries = gpd.read_file(source)
    if boundaries.empty or boundaries.crs is None:
        raise ValueError("Granica powiatu jest pusta lub nie posiada układu współrzędnych.")
    # H3 wymaga WGS84; biblioteka obsługuje także MultiPolygon i otwory.
    geom = unary_union(boundaries.to_crs("EPSG:4326").geometry)
    if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"Nieobsługiwany typ geometrii granicy: {geom.geom_type}")
    if not geom.is_valid:
        geom = geom.buffer(0)
    print(f"Granica: {source} | geometria: {geom.geom_type}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT.exists():
        OUTPUT.unlink()
    for resolution in RESOLUTIONS:
        cells = sorted(h3.geo_to_cells(mapping(geom), resolution))
        if not cells:
            raise RuntimeError(f"Brak komórek H3 dla rozdzielczości {resolution}")
        geoms = [Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(cell)]) for cell in cells]
        grid = gpd.GeoDataFrame(
            {"h3_id": cells, "resolution": [resolution] * len(cells)},
            geometry=geoms,
            crs="EPSG:4326",
        )
        layer = f"h3_r{resolution}"
        grid.to_file(OUTPUT, layer=layer, driver="GPKG")
        print(f"{layer}: {len(grid)} komórek -> {OUTPUT}")
    print("Gotowe. Komórki nie są przycinane do granicy powiatu (standard H3).")


if __name__ == "__main__":
    main()
