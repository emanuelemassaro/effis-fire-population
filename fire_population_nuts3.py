"""
Fire Population Exposure — Per NUTS3 and Per Country (2019-2023)
================================================================
For each NUTS3 region:
  1. Intersect the dissolved fire perimeter (2019-2023) with the NUTS3 boundary
  2. Sum population raster values inside that intersection  → exposed pop
  3. Sum population raster values for the full NUTS3 region → regional total
  4. Compute exposed % = exposed / regional total
Aggregate NUTS3 results up to country level.
"""

import os, zipfile, warnings
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterstats import zonal_stats
from shapely.ops import unary_union
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.ticker import FuncFormatter
import contextily as ctx

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE       = os.path.dirname(os.path.abspath(__file__))
SHP_DIR    = "/tmp/effis_shp"
DATA_DIR   = os.path.join(BASE, "data")
NUTS_PATH  = os.path.join(DATA_DIR, "NUTS3_2021_4326.geojson")
OUTPUT_DIR = os.path.join(BASE, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

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
NODATA  = -9999.0
POP_CRS = "EPSG:3035"

# ---------------------------------------------------------------------------
# 1. Load & dissolve fires (reuse extraction if already done)
# ---------------------------------------------------------------------------
print("Step 1 — Loading & dissolving fire data (2019-2023) …")

fires = gpd.read_file(os.path.join(SHP_DIR, "modis.ba.poly.shp"))
fires["year"] = pd.to_datetime(fires["FIREDATE"], errors="coerce").dt.year
fires = fires[fires["year"].between(2019, 2023)]

dissolved = gpd.GeoDataFrame(
    {"geometry": [unary_union(fires.geometry)]}, crs="EPSG:4326"
).to_crs(POP_CRS)
print(f"  {len(fires):,} fire records dissolved into single MultiPolygon")

# ---------------------------------------------------------------------------
# 2. Load NUTS3 → reproject to raster CRS
# ---------------------------------------------------------------------------
print("\nStep 2 — Loading NUTS3 regions …")
nuts = gpd.read_file(NUTS_PATH).to_crs(POP_CRS)
nuts["geometry"] = nuts.geometry.buffer(0)
print(f"  {len(nuts)} NUTS3 regions")

# ---------------------------------------------------------------------------
# 3. Intersect dissolved fire with each NUTS3 region
# ---------------------------------------------------------------------------
print("\nStep 3 — Intersecting dissolved fire with NUTS3 regions …")

# Pass single buffered geometry to avoid union_all topology issues
fire_geom = dissolved.geometry.iloc[0].buffer(0)
nuts_fire = gpd.clip(nuts, fire_geom).copy()
nuts_fire = nuts_fire[~nuts_fire.is_empty].copy()
print(f"  {len(nuts_fire)} NUTS3 regions intersect burned area")

# ---------------------------------------------------------------------------
# 4. Zonal stats — exposed and total population per NUTS3
# ---------------------------------------------------------------------------
def run_zonal(geom_series, raster_path):
    stats = zonal_stats(
        geom_series,
        raster_path,
        stats=["sum"],
        nodata=NODATA,
        all_touched=False,
    )
    return [s["sum"] or 0.0 for s in stats]

print("\nStep 4 — Running zonal statistics …")

print("  4a. Total population per NUTS3 (full extent) …")
nuts_full = nuts.set_geometry("geometry")
for key, fname in RASTERS.items():
    rpath = os.path.join(DATA_DIR, fname)
    print(f"      {LABELS[key]} …")
    nuts_full[f"tot_{key}"] = run_zonal(nuts_full.geometry, rpath)

print("  4b. Exposed population per NUTS3 (fire intersection) …")
for key, fname in RASTERS.items():
    rpath = os.path.join(DATA_DIR, fname)
    print(f"      {LABELS[key]} …")
    nuts_fire[f"exp_{key}"] = run_zonal(nuts_fire.geometry, rpath)

# ---------------------------------------------------------------------------
# 5. Merge and compute percentages
# ---------------------------------------------------------------------------
print("\nStep 5 — Building NUTS3 results table …")

tot_cols = [f"tot_{k}" for k in RASTERS]
nuts_fire = nuts_fire.merge(
    nuts_full[["NUTS_ID"] + tot_cols],
    on="NUTS_ID", how="left"
)

for key in RASTERS:
    nuts_fire[f"pct_{key}"] = (
        nuts_fire[f"exp_{key}"] / nuts_fire[f"tot_{key}"] * 100
    ).where(nuts_fire[f"tot_{key}"] > 0, 0).round(2)

nuts3_out = nuts_fire[[
    "NUTS_ID", "CNTR_CODE", "NAME_LATN",
    "exp_total",  "tot_total",  "pct_total",
    "exp_lt15",   "tot_lt15",   "pct_lt15",
    "exp_a1564",  "tot_a1564",  "pct_a1564",
    "exp_ge65",   "tot_ge65",   "pct_ge65",
    "exp_emp",    "tot_emp",    "pct_emp",
    "exp_eu_oth", "tot_eu_oth", "pct_eu_oth",
    "exp_oth",    "tot_oth",    "pct_oth",
]].copy()

nuts3_out.columns = [
    "NUTS_ID", "Country", "Name",
    "Exposed_Total",      "Regional_Total",      "Pct_Total",
    "Exposed_Under15",    "Regional_Under15",    "Pct_Under15",
    "Exposed_15_64",      "Regional_15_64",      "Pct_15_64",
    "Exposed_65plus",     "Regional_65plus",     "Pct_65plus",
    "Exposed_Employed",   "Regional_Employed",   "Pct_Employed",
    "Exposed_BornEU_Oth", "Regional_BornEU_Oth", "Pct_BornEU_Oth",
    "Exposed_BornOutsideEU", "Regional_BornOutsideEU", "Pct_BornOutsideEU",
]
for col in nuts3_out.columns:
    if col.startswith("Exposed") or col.startswith("Regional"):
        nuts3_out[col] = nuts3_out[col].round(0).astype(int)

nuts3_out = nuts3_out.sort_values(["Country", "NUTS_ID"]).reset_index(drop=True)
path_nuts3 = os.path.join(OUTPUT_DIR, "nuts3_population_exposed.csv")
nuts3_out.to_csv(path_nuts3, index=False)
print(f"  Saved → {path_nuts3}")
print(nuts3_out[["NUTS_ID","Country","Name","Exposed_Total","Pct_Total"]].to_string(index=False))

# ---------------------------------------------------------------------------
# 6. Aggregate to country level
# ---------------------------------------------------------------------------
print("\nStep 6 — Aggregating to country level …")

exp_agg = (
    nuts_fire
    .groupby("CNTR_CODE")[[f"exp_{k}" for k in RASTERS]]
    .sum()
    .reset_index()
)

tot_agg = (
    nuts_full
    .groupby("CNTR_CODE")[[f"tot_{k}" for k in RASTERS]]
    .sum()
    .reset_index()
)

country_df = exp_agg.merge(tot_agg, on="CNTR_CODE", how="outer").fillna(0)

for key in RASTERS:
    country_df[f"pct_{key}"] = (
        country_df[f"exp_{key}"] / country_df[f"tot_{key}"] * 100
    ).where(country_df[f"tot_{key}"] > 0, 0).round(2)

country_df = country_df.rename(columns={"CNTR_CODE": "Country"})
country_df = country_df.sort_values("exp_total", ascending=False).reset_index(drop=True)

country_out = country_df.copy()
country_out.columns = [
    "Country",
    "Exposed_Total",      "Exposed_Under15",    "Exposed_15_64",      "Exposed_65plus",
    "Exposed_Employed",   "Exposed_BornEU_Oth", "Exposed_BornOutsideEU",
    "Regional_Total",     "Regional_Under15",   "Regional_15_64",     "Regional_65plus",
    "Regional_Employed",  "Regional_BornEU_Oth","Regional_BornOutsideEU",
    "Pct_Total",          "Pct_Under15",        "Pct_15_64",          "Pct_65plus",
    "Pct_Employed",       "Pct_BornEU_Oth",     "Pct_BornOutsideEU",
]
for col in country_out.columns:
    if col.startswith("Exposed") or col.startswith("Regional"):
        country_out[col] = country_out[col].round(0).astype(int)

print(country_out[["Country","Exposed_Total","Regional_Total","Pct_Total"]].to_string(index=False))

# ---------------------------------------------------------------------------
# 7. Choropleth map — % total population exposed per NUTS3
# ---------------------------------------------------------------------------
print("\nStep 7 — Choropleth map (% population exposed by NUTS3) …")

nuts_map = nuts.merge(
    nuts_fire[["NUTS_ID", "pct_total"]],
    on="NUTS_ID", how="left"
)
nuts_map["pct_total"] = nuts_map["pct_total"].fillna(0)

WEB_MERC = "EPSG:3857"
nuts_wm  = nuts_map.to_crs(WEB_MERC)

fig, ax = plt.subplots(figsize=(16, 13))

nuts_wm.plot(ax=ax, color="#f0f0f0", edgecolor="#cccccc", linewidth=0.2, zorder=2)

nuts_fire_wm = nuts_wm[nuts_wm["pct_total"] > 0]
nuts_fire_wm.plot(
    column="pct_total",
    ax=ax,
    cmap="YlOrRd",
    legend=True,
    legend_kwds={
        "label": "% of regional population exposed",
        "orientation": "vertical",
        "shrink": 0.5,
        "pad": 0.01,
    },
    edgecolor="#888888",
    linewidth=0.3,
    zorder=3,
)

try:
    ctx.add_basemap(ax, crs=WEB_MERC, source=ctx.providers.CartoDB.Positron,
                    zoom=4, alpha=0.5, zorder=1)
except Exception as e:
    print(f"  Basemap not available ({e})")

ax.set_xlim(-3_000_000, 4_000_000)
ax.set_ylim(3_500_000, 9_000_000)
ax.set_axis_off()
ax.set_title(
    "Population Exposed to Fire (2019–2023) — % of NUTS3 Regional Population",
    fontsize=14, pad=10
)

choro_path = os.path.join(OUTPUT_DIR, "nuts3_choropleth_pct.png")
plt.savefig(choro_path, dpi=150, bbox_inches="tight")
plt.close()
print(f"  Saved → {choro_path}")

# ---------------------------------------------------------------------------
# 8. Bar chart — top countries by exposed population & %
# ---------------------------------------------------------------------------
print("\nStep 8 — Country bar charts (from NUTS3 aggregation) …")

top_n = 15
df_top = country_out[country_out["Exposed_Total"] > 0].head(top_n)

fig, axes = plt.subplots(1, 2, figsize=(16, 6))

ax1 = axes[0]
ax1.barh(df_top["Country"][::-1], df_top["Exposed_Total"][::-1] / 1e3,
         color="#d73027", edgecolor="white")
ax1.set_xlabel("Exposed population (thousands)")
ax1.set_title(f"Top {top_n} countries — Exposed population (2019–2023)", fontsize=12)
ax1.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:,.0f}k"))

ax2 = axes[1]
ax2.barh(df_top["Country"][::-1], df_top["Pct_Total"][::-1],
         color="#4393c3", edgecolor="white")
ax2.set_xlabel("% of national population")
ax2.set_title(f"Top {top_n} countries — % of population exposed (2019–2023)", fontsize=12)

plt.tight_layout()
bar_path = os.path.join(OUTPUT_DIR, "nuts3_country_bar_chart.png")
plt.savefig(bar_path, dpi=150, bbox_inches="tight")
plt.close()
print(f"  Saved → {bar_path}")

print("\nDone. All outputs in:", OUTPUT_DIR)
print("\nOutput files:")
for f in sorted(os.listdir(OUTPUT_DIR)):
    print(f"  {f}")
