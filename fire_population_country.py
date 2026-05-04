"""
Fire Population Exposure — Country Level (2019-2023)
=====================================================
- Dissolves all EFFIS fire perimeters 2019-2023 into a single layer (no double-counting)
- Produces a static map of fire extent over Europe
- Computes population exposed for all population classes:
    Total, Under 15, 15-64, 65+, Employed, Born in other EU MS, Born outside EU
  Both absolute counts and % of EU total are reported.
- Aggregates results per country using NUTS0/country boundaries.

Data layout expected:
    data/raw/effis/         → EFFIS shapefile (modis.ba.poly.shp or zipped)
    data/raw/population/ESTAT/ → Eurostat GeoTIFF rasters
"""

import os
import zipfile
import warnings
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterstats import zonal_stats
from shapely.ops import unary_union
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter
import contextily as ctx

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE        =  r"P:/Environment and Health/SCBTH/emanuele/crisis_exposure/data/"
EFFIS_DIR   = os.path.join(BASE,  "raw", "effis")
POP_DIR     = os.path.join(BASE, "raw", "population", "ESTAT")
BOUNDARY_DIR    = os.path.join(BASE,  "raw", "boundaries")          # for NUTS boundary
NUTS_PATH   = os.path.join(BOUNDARY_DIR, "NUTS2_2021_4326.geojson")   # background map
NUTS0_PATH  = os.path.join(BOUNDARY_DIR, "NUTS0_2021_4326.geojson")   # country boundaries
OUTPUT_DIR  = os.path.join(BASE, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

SHP_NAME    = "modis.ba.poly.shp"    # shapefile name inside EFFIS_DIR (or zip)
SHP_EXTRACT = "/tmp/effis_shp"       # extraction target if zipped

# Population rasters — same layers as fire_population_nuts3.py
RASTERS = {
    "total":    "ESTAT_OBS-VALUE-T_2021_V2.tiff",
    "lt15":     "ESTAT_OBS-VALUE-Y_LT15_2021_V2.tiff",
    "a1564":    "ESTAT_OBS-VALUE-Y_1564_2021_V2.tiff",
    "ge65":     "ESTAT_OBS-VALUE-Y_GE65_2021_V2.tiff",
    "emp":      "ESTAT_OBS-VALUE-EMP_2021_V2.tiff",
    "eu_oth":   "ESTAT_OBS-VALUE-EU_OTH_2021_V2.tiff",
    "oth":      "ESTAT_OBS-VALUE-OTH_2021_V2.tiff",
}
LABELS = {
    "total":  "Total",
    "lt15":   "Under 15",
    "a1564":  "15 to 64",
    "ge65":   "65+",
    "emp":    "Employed",
    "eu_oth": "Born in other EU MS",
    "oth":    "Born outside EU",
}

NODATA   = -9999.0
POP_CRS  = "EPSG:3035"   # raster native CRS
FIRE_CRS = "EPSG:4326"
WEB_MERC = "EPSG:3857"

# ---------------------------------------------------------------------------
# Helper: zonal sum
# ---------------------------------------------------------------------------
def zonal_sum(geometries, raster_path):
    """Return list of raster sums for each geometry; None → 0."""
    stats = zonal_stats(
        geometries,
        raster_path,
        stats=["sum"],
        nodata=NODATA,
        all_touched=False,
    )
    return [s["sum"] or 0.0 for s in stats]

# ---------------------------------------------------------------------------
# 1. Load EFFIS fire data
# ---------------------------------------------------------------------------
print("Step 1 — Loading fire data …")

f1 = os.path.join(BASE, "processed", "fires_dissolved_2019_2023.gpkg")
fires_dissolved = gpd.read_file(f1)
f2 = os.path.join(BASE, "processed", "fires_by_year_2019_2023.gpkg")
fires_by_year   = gpd.read_file(f2)


# ---------------------------------------------------------------------------
# 4. EU-wide population totals (full rasters)
# ---------------------------------------------------------------------------
print("\nStep 4 — Computing EU totals from full rasters …")
eu_totals = {}
for key, fname in RASTERS.items():
    rpath = os.path.join(POP_DIR, fname)
    with rasterio.open(rpath) as src:
        data = src.read(1).astype(float)
        data[data == NODATA] = np.nan
        eu_totals[key] = float(np.nansum(data))
    print(f"    {LABELS[key]:>22s}: {eu_totals[key]:>14,.0f}")

# ---------------------------------------------------------------------------
# 5. Exposed population — dissolved fire extent (EU-wide)
# ---------------------------------------------------------------------------
print("\nStep 5 — Computing EU-wide exposed population …")
dissolved_3035 = fires_dissolved.to_crs(POP_CRS)

exposed_eu = {}
for key, fname in RASTERS.items():
    rpath = os.path.join(POP_DIR, fname)
    val = zonal_sum(dissolved_3035, rpath)[0]
    exposed_eu[key] = val
    pct = (val / eu_totals[key] * 100) if eu_totals[key] else 0
    print(f"    {LABELS[key]:>22s}: {val:>12,.0f}  ({pct:.2f}% of EU)")

# ---------------------------------------------------------------------------
# 6. Country-level exposure via NUTS0 boundaries
# ---------------------------------------------------------------------------
print("\nStep 6 — Country-level exposure …")

# Load country (NUTS0) boundaries
if os.path.exists(NUTS0_PATH):
    countries = gpd.read_file(NUTS0_PATH).to_crs(POP_CRS)
else:
    # Fallback: dissolve NUTS2 by country code
    print("  NUTS0 file not found — dissolving NUTS2 to country level …")
    nuts2 = gpd.read_file(NUTS_PATH).to_crs(POP_CRS)
    nuts2["CNTR_CODE"] = nuts2["NUTS_ID"].str[:2]
    countries = nuts2.dissolve(by="CNTR_CODE").reset_index()[["CNTR_CODE", "geometry"]]
    countries = countries.rename(columns={"CNTR_CODE": "NUTS_ID"})
    if "CNTR_CODE" not in countries.columns:
        countries["CNTR_CODE"] = countries["NUTS_ID"]

# Ensure CNTR_CODE column exists
if "CNTR_CODE" not in countries.columns:
    countries["CNTR_CODE"] = countries["NUTS_ID"].str[:2]

countries["geometry"] = countries.geometry.buffer(0)

# Intersect dissolved fire with each country
fire_geom_3035 = dissolved_3035.geometry.iloc[0].buffer(0)
countries_fire = gpd.clip(countries, fire_geom_3035).copy()
countries_fire = countries_fire[~countries_fire.is_empty].copy()
print(f"  {len(countries_fire)} countries have burned area")

# Exposed population per country
print("  Running zonal stats on fire-clipped country geometries …")
for key, fname in RASTERS.items():
    rpath = os.path.join(POP_DIR, fname)
    countries_fire[f"exp_{key}"] = zonal_sum(countries_fire.geometry, rpath)

# Total population per country (full extent)
print("  Running zonal stats on full country geometries …")
for key, fname in RASTERS.items():
    rpath = os.path.join(POP_DIR, fname)
    countries[f"tot_{key}"] = zonal_sum(countries.geometry, rpath)

# Merge totals into fire slice
id_col = "CNTR_CODE" if "CNTR_CODE" in countries.columns else "NUTS_ID"
tot_cols = [f"tot_{k}" for k in RASTERS]
countries_fire = countries_fire.merge(
    countries[[id_col] + tot_cols],
    on=id_col, how="left"
)

# Compute percentages
for key in RASTERS:
    countries_fire[f"pct_{key}"] = (
        countries_fire[f"exp_{key}"] / countries_fire[f"tot_{key}"] * 100
    ).where(countries_fire[f"tot_{key}"] > 0, 0).round(2)

# ---------------------------------------------------------------------------
# 7. Build and save country results table
# ---------------------------------------------------------------------------
print("\nStep 7 — Building country results table …")

keep = [id_col] + \
       [f"exp_{k}" for k in RASTERS] + \
       [f"tot_{k}" for k in RASTERS] + \
       [f"pct_{k}" for k in RASTERS]
country_out = countries_fire[keep].copy()

# Rename columns for readability
col_map = {id_col: "Country"}
for key in RASTERS:
    lbl = LABELS[key].replace(" ", "_")
    col_map[f"exp_{key}"] = f"Exposed_{lbl}"
    col_map[f"tot_{key}"] = f"National_{lbl}"
    col_map[f"pct_{key}"] = f"Pct_{lbl}"
country_out = country_out.rename(columns=col_map)

# Round population columns
for col in country_out.columns:
    if col.startswith("Exposed_") or col.startswith("National_"):
        country_out[col] = country_out[col].round(0).astype(int)

country_out = country_out.sort_values("Exposed_Total", ascending=False).reset_index(drop=True)

csv_path = os.path.join(OUTPUT_DIR, "country_population_exposed.csv")
country_out.to_csv(csv_path, index=False)
print(f"  Saved → {csv_path}")
print(country_out[["Country", "Exposed_Total", "National_Total", "Pct_Total"]].to_string(index=False))

# ---------------------------------------------------------------------------
# 8. EU-wide summary table
# ---------------------------------------------------------------------------
print("\nStep 8 — EU-wide summary table …")

records = []
for key in RASTERS:
    records.append({
        "Population class":   LABELS[key],
        "Exposed":            int(round(exposed_eu[key])),
        "EU total":           int(round(eu_totals[key])),
        "Exposed %":          round(exposed_eu[key] / eu_totals[key] * 100, 2)
                              if eu_totals[key] else 0.0,
    })
df_eu = pd.DataFrame(records)
print("\n" + df_eu.to_string(index=False))

eu_csv = os.path.join(OUTPUT_DIR, "eu_population_exposed.csv")
df_eu.to_csv(eu_csv, index=False)
print(f"  Saved → {eu_csv}")

# ---------------------------------------------------------------------------
# 9. Charts
# ---------------------------------------------------------------------------
print("\nStep 9 — Creating charts …")

# --- 9a. EU-wide bar chart by population class ---
fig, axes = plt.subplots(1, 2, figsize=(16, 6))

colors_abs = ["#2166ac", "#4393c3", "#92c5de", "#d1e5f0", "#f4a582", "#d6604d", "#b2182b"]
colors_pct = ["#1a9850", "#66bd63", "#a6d96a", "#d9ef8b", "#fdae61", "#f46d43", "#d73027"]

ax1 = axes[0]
bars = ax1.bar(df_eu["Population class"], df_eu["Exposed"] / 1e6,
               color=colors_abs, edgecolor="white", linewidth=0.8)
ax1.set_title("Population Exposed to Fire (2019–2023)\nby Population Class — EU total",
              fontsize=12)
ax1.set_ylabel("Millions of people")
ax1.set_xticklabels(df_eu["Population class"], rotation=25, ha="right", fontsize=9)
for bar in bars:
    h = bar.get_height()
    ax1.text(bar.get_x() + bar.get_width() / 2, h + 0.01,
             f"{h:.2f}M", ha="center", va="bottom", fontsize=8)

ax2 = axes[1]
bars2 = ax2.bar(df_eu["Population class"], df_eu["Exposed %"],
                color=colors_pct, edgecolor="white", linewidth=0.8)
ax2.set_title("% of EU Population Exposed to Fire (2019–2023)\nby Population Class",
              fontsize=12)
ax2.set_ylabel("% of EU class total")
ax2.set_xticklabels(df_eu["Population class"], rotation=25, ha="right", fontsize=9)
for bar in bars2:
    h = bar.get_height()
    ax2.text(bar.get_x() + bar.get_width() / 2, h + 0.01,
             f"{h:.2f}%", ha="center", va="bottom", fontsize=8)

plt.tight_layout()
chart1_path = os.path.join(OUTPUT_DIR, "eu_population_exposed_chart.png")
plt.savefig(chart1_path, dpi=150, bbox_inches="tight")
plt.close()
print(f"  Saved → {chart1_path}")

# --- 9b. Country bar charts — top 15 ---
top_n = 15
df_top = country_out.head(top_n)

fig, axes = plt.subplots(1, 2, figsize=(16, 6))

ax1 = axes[0]
ax1.barh(df_top["Country"][::-1], df_top["Exposed_Total"][::-1] / 1e3,
         color="#d73027", edgecolor="white")
ax1.set_xlabel("Exposed population (thousands)")
ax1.set_title(f"Top {top_n} Countries — Exposed Population (2019–2023)", fontsize=12)
ax1.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:,.0f}k"))

ax2 = axes[1]
ax2.barh(df_top["Country"][::-1], df_top["Pct_Total"][::-1],
         color="#4393c3", edgecolor="white")
ax2.set_xlabel("% of national population")
ax2.set_title(f"Top {top_n} Countries — % of Population Exposed (2019–2023)", fontsize=12)

plt.tight_layout()
chart2_path = os.path.join(OUTPUT_DIR, "country_population_exposed_chart.png")
plt.savefig(chart2_path, dpi=150, bbox_inches="tight")
plt.close()
print(f"  Saved → {chart2_path}")

# --- 9c. Stacked bar — exposed population by class per country (top 10) ---
top10 = country_out.head(10)
age_keys = ["lt15", "a1564", "ge65"]
age_cols = [f"Exposed_{LABELS[k].replace(' ', '_')}" for k in age_keys]
age_lbls = [LABELS[k] for k in age_keys]
age_colors = ["#4393c3", "#2166ac", "#053061"]

fig, ax = plt.subplots(figsize=(14, 6))
bottom = np.zeros(len(top10))
for col, lbl, clr in zip(age_cols, age_lbls, age_colors):
    vals = top10[col].values / 1e3
    ax.bar(top10["Country"], vals, bottom=bottom, label=lbl, color=clr, edgecolor="white")
    bottom += vals

ax.set_ylabel("Exposed population (thousands)")
ax.set_title("Exposed Population by Age Group — Top 10 Countries (2019–2023)", fontsize=12)
ax.legend(title="Age group", loc="upper right")
ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: x))
plt.tight_layout()
chart3_path = os.path.join(OUTPUT_DIR, "country_age_stacked_chart.png")
plt.savefig(chart3_path, dpi=150, bbox_inches="tight")
plt.close()
print(f"  Saved → {chart3_path}")

# ---------------------------------------------------------------------------
print("\nDone. All outputs in:", OUTPUT_DIR)
print("\nOutput files:")
for f in sorted(os.listdir(OUTPUT_DIR)):
    print(f"  {f}")