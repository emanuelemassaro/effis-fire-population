import os
import requests

BASE        =  r"P:/Environment and Health/SCBTH/emanuele/crisis_exposure/data/"

OUTPUT_DIR = os.path.join(BASE, 'raw', 'boundaries') # adjust to your path

# GISCO NUTS boundaries — all levels, 1:1M resolution, WGS84
urls = {
    "NUTS0_2021_4326.geojson": "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_01M_2021_4326_LEVL_0.geojson",
    "NUTS2_2021_4326.geojson": "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_01M_2021_4326_LEVL_2.geojson",
    "NUTS3_2021_4326.geojson": "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_01M_2021_4326_LEVL_3.geojson",
}

os.makedirs(OUTPUT_DIR, exist_ok=True)

for filename, url in urls.items():
    out_path = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(out_path):
        print(f"  Already exists, skipping: {filename}")
        continue
    print(f"  Downloading {filename} ...")
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(response.text)
    print(f"  Saved → {out_path}")

print("\nDone.")