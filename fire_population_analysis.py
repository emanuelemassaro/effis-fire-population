"""
Fire Population Exposure Analysis (2019-2023)
=============================================
- Dissolves all fire perimeters 2019-2023 into a single layer (no double-counting)
- Produces a static map of fire extent over Europe
- Computes population exposed by age group (total counts + % of EU total)
"""

import os
import zipfile
import warnings
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.mask import mask as rio_mask
from rasterstats import zonal_stats
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
from shapely.ops import unary_union
import contextily as ctx

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE = os.path.dirname(os.path.abspath(__file__))
ZIP_PATH    = os.path.join(BASE, "effis_layer.zip")
SHP_DIR     = "/tmp/effis_shp"
DATA_DIR    = os.path.join(BASE, "data")
NUTS_PATH   = os.path.join(DATA_DIR, "NUTS2_2021_4326.geojson")
OUTPUT_DIR  = os.path.join(BASE, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

RASTERS = {
    "Total":    "ESTAT_OBS-VALUE-T_2021_V2.tiff",
    "Under 15": "ESTAT_OBS-VALUE-Y_LT15_2021_V2.tiff",
    "15 to 64": "ESTAT_OBS-VALUE-Y_1564_2021_V2.tiff",
    "65+":      "ESTAT_OBS-VALUE-Y_GE65_2021_V2.tiff",
}
NODATA = -9999.0
POP_CRS = "EPSG:3035"   # raster CRS
FIRE_CRS = "EPSG:4326"  # shapefile CRS

# ---------------------------------------------------------------------------
# 1. Extract & filter fire shapefile
# ---------------------------------------------------------------------------
print("Step 1 — Loading fire data …")
if not os.path.exists(os.path.join(SHP_DIR, "modis.ba.poly.shp")):
    with zipfile.ZipFile(ZIP_PATH) as z:
        z.extractall(SHP_DIR)

fires = gpd.read_file(os.path.join(SHP_DIR, "modis.ba.poly.shp"))
fires["FIREDATE"] = pd.to_datetime(fires["FIREDATE"], errors="coerce")
fires["year"] = fires["FIREDATE"].dt.year

fires_filtered = fires[fires["year"].between(2019, 2023)].copy()
print(f"  Total fire records 2019-2023: {len(fires_filtered):,}")
print(f"  Records per year:\n{fires_filtered['year'].value_counts().sort_index().to_string()}")

# ---------------------------------------------------------------------------
# 2. Dissolve fires — union into a single geometry (no double-counting)
# ---------------------------------------------------------------------------
print("\nStep 2 — Dissolving fire perimeters …")
dissolved_geom = unary_union(fires_filtered.geometry)
fires_dissolved = gpd.GeoDataFrame(
    {"geometry": [dissolved_geom]},
    crs=FIRE_CRS
)
area_ha = fires_filtered["AREA_HA"].astype(float, errors="ignore")
print(f"  Dissolved geometry type: {dissolved_geom.geom_type}")

# Also dissolve per year for the map legend
fires_by_year = (
    fires_filtered
    .dissolve(by="year")
    .reset_index()[["year", "geometry"]]
)

# ---------------------------------------------------------------------------
# 3. Static map
# ---------------------------------------------------------------------------
print("\nStep 3 — Creating static map …")

# Load NUTS2 for background
nuts = gpd.read_file(NUTS_PATH)

# Reproject everything to Web Mercator for contextily basemap
WEB_MERC = "EPSG:3857"
nuts_wm     = nuts.to_crs(WEB_MERC)
fires_wm    = fires_filtered.to_crs(WEB_MERC)
dissolved_wm = fires_dissolved.to_crs(WEB_MERC)
by_year_wm  = fires_by_year.to_crs(WEB_MERC)

# Europe bounding box (approximate)
xmin, ymin, xmax, ymax = -3_000_000, 3_500_000, 4_000_000, 9_000_000

year_colors = {
    2019: "#fee08b",
    2020: "#fdae61",
    2021: "#f46d43",
    2022: "#d73027",
    2023: "#a50026",
}

fig, ax = plt.subplots(figsize=(16, 14))

# NUTS2 outline
nuts_wm.boundary.plot(ax=ax, linewidth=0.3, color="#888888", zorder=2)

# Fire perimeters per year (stacked — latest year on top)
for year in sorted(year_colors):
    subset = by_year_wm[by_year_wm["year"] == year]
    if not subset.empty:
        subset.plot(
            ax=ax,
            color=year_colors[year],
            alpha=0.7,
            edgecolor="none",
            zorder=3,
        )

# Dissolved outline
dissolved_wm.boundary.plot(
    ax=ax, linewidth=0.6, color="#600000", linestyle="--", zorder=4, label="Dissolved extent"
)

# Basemap
try:
    ctx.add_basemap(
        ax, crs=WEB_MERC,
        source=ctx.providers.CartoDB.Positron,
        zoom=4, alpha=0.6, zorder=1
    )
except Exception as e:
    print(f"  Basemap not available ({e}), skipping.")

ax.set_xlim(xmin, xmax)
ax.set_ylim(ymin, ymax)
ax.set_axis_off()

# Legend
legend_patches = [
    mpatches.Patch(facecolor=year_colors[y], edgecolor="none", alpha=0.8, label=str(y))
    for y in sorted(year_colors)
]
legend_patches.append(
    Line2D([0], [0], color="#600000", linewidth=1, linestyle="--", label="Dissolved extent")
)
ax.legend(
    handles=legend_patches,
    title="Fire year",
    loc="lower left",
    fontsize=10,
    title_fontsize=11,
    framealpha=0.9,
)

ax.set_title("Burned Areas in Europe — EFFIS MODIS (2019–2023)", fontsize=16, pad=12)

map_path = os.path.join(OUTPUT_DIR, "fire_map_2019_2023.png")
plt.savefig(map_path, dpi=150, bbox_inches="tight")
plt.close()
print(f"  Map saved → {map_path}")

# ---------------------------------------------------------------------------
# 4. Population exposure via rasterstats
# ---------------------------------------------------------------------------
print("\nStep 4 — Computing population exposed …")

# Reproject dissolved fire boundary to raster CRS (EPSG:3035)
dissolved_3035 = fires_dissolved.to_crs(POP_CRS)
geom_3035 = [dissolved_3035.geometry.iloc[0]]

def sum_raster_in_mask(raster_path, geom_list):
    """Return the sum of raster values inside geom_list, ignoring nodata."""
    stats = zonal_stats(
        geom_list,
        raster_path,
        stats=["sum"],
        nodata=NODATA,
        all_touched=False,  # only cells whose centre falls inside
    )
    return stats[0]["sum"] or 0.0

# Total EU population (full raster, no mask)
print("  Computing EU totals from full rasters …")
eu_totals = {}
for label, fname in RASTERS.items():
    rpath = os.path.join(DATA_DIR, fname)
    with rasterio.open(rpath) as src:
        data = src.read(1).astype(float)
        data[data == NODATA] = np.nan
        eu_totals[label] = np.nansum(data)
    print(f"    EU {label}: {eu_totals[label]:,.0f}")

# Population inside dissolved fire boundary
print("\n  Computing exposed population inside dissolved fire extent …")
exposed = {}
for label, fname in RASTERS.items():
    rpath = os.path.join(DATA_DIR, fname)
    val = sum_raster_in_mask(rpath, dissolved_3035)
    exposed[label] = val
    pct = (val / eu_totals[label] * 100) if eu_totals[label] else 0
    print(f"    {label}: {val:>12,.0f}  ({pct:.2f}% of EU)")

# ---------------------------------------------------------------------------
# 5. Build results table and save
# ---------------------------------------------------------------------------
print("\nStep 5 — Building results table …")

records = []
for label in RASTERS:
    records.append({
        "Age group":            label,
        "Exposed population":   int(round(exposed[label])),
        "EU total":             int(round(eu_totals[label])),
        "Exposed %":            round(exposed[label] / eu_totals[label] * 100, 2)
                                if eu_totals[label] else 0.0,
    })

df_results = pd.DataFrame(records)
print("\n" + df_results.to_string(index=False))

csv_path = os.path.join(OUTPUT_DIR, "population_exposed_2019_2023.csv")
df_results.to_csv(csv_path, index=False)
print(f"\nResults saved → {csv_path}")

# ---------------------------------------------------------------------------
# 6. Bar chart — exposed population by age group
# ---------------------------------------------------------------------------
print("\nStep 6 — Creating population bar chart …")

age_groups = ["Under 15", "15 to 64", "65+"]
df_age = df_results[df_results["Age group"].isin(age_groups)].set_index("Age group")

fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# Absolute counts
ax1 = axes[0]
bars = ax1.bar(
    df_age.index,
    df_age["Exposed population"] / 1e6,
    color=["#4393c3", "#2166ac", "#053061"],
    edgecolor="white", linewidth=0.8
)
ax1.set_title("Population Exposed to Fire (2019–2023)\nby Age Group", fontsize=13)
ax1.set_ylabel("Millions of people")
ax1.set_ylim(0, df_age["Exposed population"].max() / 1e6 * 1.2)
for bar in bars:
    h = bar.get_height()
    ax1.text(
        bar.get_x() + bar.get_width() / 2, h + 0.02,
        f"{h:.2f}M", ha="center", va="bottom", fontsize=10
    )

# Percentage of EU total
ax2 = axes[1]
bars2 = ax2.bar(
    df_age.index,
    df_age["Exposed %"],
    color=["#d6604d", "#b2182b", "#67001f"],
    edgecolor="white", linewidth=0.8
)
ax2.set_title("% of EU Population Exposed to Fire (2019–2023)\nby Age Group", fontsize=13)
ax2.set_ylabel("% of EU total")
ax2.set_ylim(0, df_age["Exposed %"].max() * 1.3)
for bar in bars2:
    h = bar.get_height()
    ax2.text(
        bar.get_x() + bar.get_width() / 2, h + 0.005,
        f"{h:.2f}%", ha="center", va="bottom", fontsize=10
    )

plt.tight_layout()
chart_path = os.path.join(OUTPUT_DIR, "population_exposed_chart.png")
plt.savefig(chart_path, dpi=150, bbox_inches="tight")
plt.close()
print(f"  Chart saved → {chart_path}")

print("\nDone. All outputs in:", OUTPUT_DIR)
