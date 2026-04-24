"""
Bar charts — Population groups exposed to fire (2019-2023)
Groups: Non-Employed (Total - EMP), Born in other EU MS, Born outside EU
"""

import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

BASE       = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE, "output")

# ---------------------------------------------------------------------------
# Load & aggregate NUTS3 → country
# ---------------------------------------------------------------------------
df = pd.read_csv(os.path.join(OUTPUT_DIR, "nuts3_population_exposed.csv"))

agg_cols = [c for c in df.columns if c.startswith("Exposed_") or c.startswith("Regional_")]
country = df.groupby("Country")[agg_cols].sum().reset_index()

# Derive Non-employed
country["Exposed_NonEmployed"]  = country["Exposed_Total"]  - country["Exposed_Employed"]
country["Regional_NonEmployed"] = country["Regional_Total"] - country["Regional_Employed"]

# Recompute percentages
for key, reg in [
    ("NonEmployed", "NonEmployed"),
    ("BornEU_Oth",  "BornEU_Oth"),
    ("BornOutsideEU", "BornOutsideEU"),
]:
    denom = country[f"Regional_{reg}"]
    country[f"Pct_{key}"] = (
        country[f"Exposed_{key}"] / denom * 100
    ).where(denom > 0, 0).round(2)

# Top-15 countries by total exposed (consistent sort across charts)
top15 = country[country["Exposed_Total"] > 0].nlargest(15, "Exposed_Total").copy()

GROUPS = [
    ("NonEmployed",   "Non-Employed",          "#e74c3c"),
    ("BornEU_Oth",    "Born in other EU MS",   "#3498db"),
    ("BornOutsideEU", "Born outside EU",        "#27ae60"),
]

fmt_k = mticker.FuncFormatter(lambda x, _: f"{x:,.0f}k")

# ---------------------------------------------------------------------------
# Figure 1 — Absolute exposed population
# ---------------------------------------------------------------------------
fig, axes = plt.subplots(1, 3, figsize=(20, 7))
fig.suptitle("Population Groups Exposed to Fire (2019–2023) — Absolute Numbers",
             fontsize=14, fontweight="bold", y=1.02)

for ax, (key, label, color) in zip(axes, GROUPS):
    data = top15.sort_values(f"Exposed_{key}", ascending=True)
    ax.barh(data["Country"], data[f"Exposed_{key}"] / 1e3, color=color,
            edgecolor="white", linewidth=0.5)
    ax.set_xlabel("Exposed population (thousands)")
    ax.set_title(label, fontsize=11, pad=8)
    ax.xaxis.set_major_formatter(fmt_k)
    ax.spines[["top", "right"]].set_visible(False)

plt.tight_layout()
out1 = os.path.join(OUTPUT_DIR, "groups_absolute.png")
plt.savefig(out1, dpi=150, bbox_inches="tight")
plt.close()
print(f"Saved → {out1}")

# ---------------------------------------------------------------------------
# Figure 2 — % of each group exposed
# ---------------------------------------------------------------------------
fig, axes = plt.subplots(1, 3, figsize=(20, 7))
fig.suptitle("Population Groups Exposed to Fire (2019–2023) — % of Group Exposed",
             fontsize=14, fontweight="bold", y=1.02)

for ax, (key, label, color) in zip(axes, GROUPS):
    data = top15.sort_values(f"Pct_{key}", ascending=True)
    ax.barh(data["Country"], data[f"Pct_{key}"], color=color,
            edgecolor="white", linewidth=0.5)
    ax.set_xlabel("% of group population exposed")
    ax.set_title(label, fontsize=11, pad=8)
    ax.spines[["top", "right"]].set_visible(False)

plt.tight_layout()
out2 = os.path.join(OUTPUT_DIR, "groups_pct_exposed.png")
plt.savefig(out2, dpi=150, bbox_inches="tight")
plt.close()
print(f"Saved → {out2}")

# ---------------------------------------------------------------------------
# Figure 3 — Stacked bars: exposed vs non-exposed, one panel per group
# ---------------------------------------------------------------------------
fig, axes = plt.subplots(1, 3, figsize=(20, 7))
fig.suptitle("Population Groups Exposed to Fire (2019–2023) — Exposed vs. Total",
             fontsize=14, fontweight="bold", y=1.02)

for ax, (key, label, color) in zip(axes, GROUPS):
    data = top15.sort_values(f"Exposed_{key}", ascending=True).copy()
    exposed     = data[f"Exposed_{key}"]  / 1e3
    non_exposed = (data[f"Regional_{key}"] - data[f"Exposed_{key}"]) / 1e3

    ax.barh(data["Country"], non_exposed, color="#d0d0d0",
            edgecolor="white", linewidth=0.5, label="Not exposed")
    ax.barh(data["Country"], exposed, left=non_exposed, color=color,
            edgecolor="white", linewidth=0.5, label="Exposed")

    ax.set_xlabel("Population (thousands)")
    ax.set_title(label, fontsize=11, pad=8)
    ax.xaxis.set_major_formatter(fmt_k)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="lower right", fontsize=8, framealpha=0.7)

plt.tight_layout()
out3 = os.path.join(OUTPUT_DIR, "groups_stacked.png")
plt.savefig(out3, dpi=150, bbox_inches="tight")
plt.close()
print(f"Saved → {out3}")

print("\nDone.")
