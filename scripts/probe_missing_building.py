"""Probe OSM + local context for the gap east of giant trees T232/T234."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Polygon, box

ROOT = Path(r"D:\CFD_Shadow")
OX, OY = 836318.0, 818150.0


def main() -> None:
    to_hk = Transformer.from_crs("EPSG:4326", "EPSG:2326", always_xy=True)
    south, west, north, east = 22.30310, 114.17930, 22.30440, 114.18070
    query = f"""[out:json][timeout:90];
(
  way({south},{west},{north},{east});
  relation({south},{west},{north},{east});
);
out tags geom;
"""
    req = urllib.request.Request(
        "https://overpass-api.de/api/interpreter",
        data=query.encode(),
        headers={"User-Agent": "cfd-shadow/0.1"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())

    print("overpass elements", len(data.get("elements", [])))
    region = box(225, 115, 295, 185)
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        coords = []
        for p in geom:
            x, y = to_hk.transform(p["lon"], p["lat"])
            coords.append((x - OX, y - OY))
        cx = sum(c[0] for c in coords) / len(coords)
        cy = sum(c[1] for c in coords) / len(coords)
        if not (210 <= cx <= 310 and 100 <= cy <= 210):
            continue
        keys = (
            "building",
            "building:part",
            "name",
            "name:en",
            "amenity",
            "landuse",
            "man_made",
            "highway",
            "barrier",
            "levels",
            "height",
            "building:levels",
        )
        slim = {k: tags[k] for k in keys if k in tags}
        area = None
        if len(coords) >= 4 and ("building" in tags or "building:part" in tags):
            try:
                area = round(abs(Polygon(coords).area), 1)
            except Exception:
                area = None
        print(
            el["type"],
            el["id"],
            "c",
            round(cx, 1),
            round(cy, 1),
            "n",
            len(coords),
            "area",
            area,
            slim,
        )

    # Compare with wind package buildings (CFD domain)
    wind_b = json.loads((ROOT / "data/wind/buildings.json").read_text(encoding="utf-8"))
    print("\nwind buildings near gap:")
    for b in wind_b.get("buildings", []):
        ring = b.get("ring") or []
        if len(ring) < 3:
            continue
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        if 210 <= cx <= 310 and 100 <= cy <= 210:
            print(b.get("osm_id"), b.get("name"), b.get("height_m"), round(cx, 1), round(cy, 1))


if __name__ == "__main__":
    main()
