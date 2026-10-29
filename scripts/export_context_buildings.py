"""Export wider OSM building footprints + highway/path lines for campus context.

Target ~1.5 km around PolyU so the dashboard is not clipped to the CFD patch.
"""

from __future__ import annotations

import json
import math
import urllib.request
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Polygon
from shapely.ops import transform as shp_transform

ROOT = Path(r"D:\CFD_Shadow")
OUT = ROOT / "data" / "buildings"
PUBLIC = ROOT / "dashboard" / "public" / "buildings"
# Align with wind / crowns origin
ORIGIN = (836318.0, 818150.0, 2.0)
# PolyU approx WGS84 center
CENTER_LAT, CENTER_LON = 22.3046, 114.1797
RADIUS_M = 1500.0
CACHE = ROOT / "data" / "buildings" / "osm_raw_1p5km.json"


def bbox_from_radius(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(0.2, math.cos(math.radians(lat))))
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon


def fetch_osm(south: float, west: float, north: float, east: float, cache: Path) -> dict:
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    # Highways/rail only — buildings come from LandsD. Smaller query = fewer timeouts.
    query = f"""[out:json][timeout:240];
(
  way["highway"]({south},{west},{north},{east});
  way["railway"]({south},{west},{north},{east});
);
out tags geom;
"""
    urls = (
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    )
    last = None
    for url in urls:
        try:
            print(f"  Overpass try {url} …")
            req = urllib.request.Request(
                url,
                data=query.encode("utf-8"),
                headers={"User-Agent": "cfd-shadow/0.2 (research)"},
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data), encoding="utf-8")
            return data
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"  Overpass fail: {exc}")
    raise RuntimeError(f"Overpass failed: {last}")


def parse_height(tags: dict) -> float:
    raw = tags.get("height")
    if raw:
        try:
            return max(float(str(raw).lower().replace("m", "").strip()), 3.0)
        except ValueError:
            pass
    levels = tags.get("building:levels") or tags.get("levels")
    if levels:
        try:
            return max(float(levels) * 3.2, 3.0)
        except ValueError:
            pass
    return 12.0


def main() -> int:
    south, west, north, east = bbox_from_radius(CENTER_LAT, CENTER_LON, RADIUS_M)
    print(f"Fetching OSM ~{RADIUS_M:.0f}m bbox SWN E {south:.5f},{west:.5f},{north:.5f},{east:.5f}")
    data = fetch_osm(south, west, north, east, CACHE)
    to_hk = Transformer.from_crs("EPSG:4326", "EPSG:2326", always_xy=True)
    ox, oy, _oz = ORIGIN

    buildings = []
    roads = []
    for el in data.get("elements", []):
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        tags = el.get("tags") or {}
        coords_ll = [(p["lon"], p["lat"]) for p in geom]
        is_buildingish = (
            "building" in tags
            or "building:part" in tags
            or tags.get("amenity") == "library"
        )
        if is_buildingish and len(coords_ll) >= 4:
            poly = Polygon(coords_ll)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty:
                continue
            poly_hk = shp_transform(lambda x, y, z=None: to_hk.transform(x, y), poly)
            if poly_hk.is_empty or poly_hk.area < 8.0:
                continue
            ring = [
                [round(float(x) - ox, 2), round(float(y) - oy, 2)]
                for x, y in list(poly_hk.exterior.coords)[:-1]
            ]
            if len(ring) < 3:
                continue
            name = str(tags.get("name") or tags.get("name:en") or "")
            height = parse_height(tags)
            # Libraries often lack height/levels tags — keep a campus-scale mass.
            if tags.get("amenity") == "library" or "library" in name.lower() or "圖書館" in name:
                height = max(height, 28.0)
            buildings.append(
                {
                    "osm_id": int(el.get("id") or 0),
                    "name": name,
                    "height_m": round(height, 2),
                    "ring": ring,
                }
            )
        elif tags.get("highway") or tags.get("railway"):
            line = []
            for lon, lat in coords_ll:
                x, y = to_hk.transform(lon, lat)
                line.append([round(float(x) - ox, 2), round(float(y) - oy, 2)])
            if len(line) < 2:
                continue
            roads.append(
                {
                    "osm_id": int(el.get("id") or 0),
                    "kind": "railway" if tags.get("railway") else "highway",
                    "highway": tags.get("highway") or tags.get("railway") or "",
                    "name": str(tags.get("name") or tags.get("name:en") or ""),
                    "line": line,
                }
            )

    OUT.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "crs": "local_metres_from_domain_origin",
        "origin_hk80": list(ORIGIN),
        "radius_m": RADIUS_M,
        "center_wgs84": [CENTER_LON, CENTER_LAT],
        "n_buildings": len(buildings),
        "n_roads": len(roads),
        "buildings": buildings,
        "roads": roads,
        "note": "OSM context (~1.5km). Footprints still extruded; replace with LandsD 3D shapes next for true massing.",
    }
    out_json = OUT / "context_1p5km.json"
    out_json.write_text(json.dumps(payload), encoding="utf-8")
    (PUBLIC / "context_1p5km.json").write_text(json.dumps(payload), encoding="utf-8")
    print(f"Wrote {len(buildings)} buildings, {len(roads)} road/rail ways → {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
