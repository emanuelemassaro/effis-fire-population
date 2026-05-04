"""
Dissolve EFFIS fire perimeters 2019-2023 into a single GeoPackage/GeoJSON.
Run this once — then load the output in all your analysis scripts.
"""

import os
import zipfile
import pandas as pd
import geopandas as gpd
from shapely.ops import unary_union

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE        =  r"P:/Environment and Health/SCBTH/emanuele/crisis_exposure/"
EFFIS_DIR = os.path.join(BASE, "data", "raw", "effis")
OUT_DIR   = os.path.join(BASE, "data", "processed")
os.makedirs(OUT_DIR, exist_ok=True)

SHP_NAME    = "modis.ba.poly.shp"
SHP_EXTRACT = r"C:/tmp/effis_shp"

# ---------------------------------------------------------------------------
# 1. Load EFFIS
# ---------------------------------------------------------------------------
print("Loading EFFIS data ...")

shp_path = os.path.join(EFFIS_DIR, SHP_NAME)
if not os.path.exists(shp_path):
    zips = [f for f in os.listdir(EFFIS_DIR) if f.endswith(".zip")]
    if zips:
        os.makedirs(SHP_EXTRACT, exist_ok=True)
        with zipfile.ZipFile(os.path.join(EFFIS_DIR, zips[0])) as z:
            z.extractall(SHP_EXTRACT)
        shp_path = os.path.join(SHP_EXTRACT, SHP_NAME)
    else:
        raise FileNotFoundError(f"No shapefile or zip found in {EFFIS_DIR}")

fires = gpd.read_file(shp_path)
fires["FIREDATE"] = pd.to_datetime(fires["FIREDATE"], errors="coerce")
fires["year"] = fires["FIREDATE"].dt.year
fires = fires[fires["year"].between(2019, 2023)].copy()
print(f"  {len(fires):,} fire records (2019-2023)")
print(fires["year"].value_counts().sort_index().to_string())

# ---------------------------------------------------------------------------
# 2. Dissolve — single geometry (no double counting)
# ---------------------------------------------------------------------------
print("\nDissolving all fires into single geometry ...")
dissolved = gpd.GeoDataFrame(
    {"geometry": [unary_union(fires.geometry)]},
    crs="EPSG:4326"
)
print(f"  Done — geometry type: {dissolved.geometry.iloc[0].geom_type}")

# ---------------------------------------------------------------------------
# 3. Dissolve per year (useful for maps)
# ---------------------------------------------------------------------------
print("Dissolving per year ...")
by_year = (
    fires.dissolve(by="year")
    .reset_index()[["year", "geometry"]]
)
print(f"  {len(by_year)} yearly layers")

# ---------------------------------------------------------------------------
# 4. Save
# ---------------------------------------------------------------------------
# Single dissolved — GeoPackage (robust) + GeoJSON (portable)
gpkg_path = os.path.join(OUT_DIR, "fires_dissolved_2019_2023.gpkg")
dissolved.to_file(gpkg_path, driver="GPKG")
print(f"\nSaved → {gpkg_path}")

geojson_path = os.path.join(OUT_DIR, "fires_dissolved_2019_2023.geojson")
dissolved.to_file(geojson_path, driver="GeoJSON")
print(f"Saved → {geojson_path}")

# Per-year dissolved
year_path = os.path.join(OUT_DIR, "fires_by_year_2019_2023.gpkg")
by_year.to_file(year_path, driver="GPKG")
print(f"Saved → {year_path}")

print("\nDone. You can now load these files directly in your analysis scripts:")
print(f"  dissolved = gpd.read_file(r'{gpkg_path}')")
print(f"  by_year   = gpd.read_file(r'{year_path}')")