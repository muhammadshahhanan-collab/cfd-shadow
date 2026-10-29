"""Add Pao Yue-kong Library + other untagged campus masses into context buildings.

Root cause: OSM marks the library as amenity=library without building=*, so the
earlier context export skipped the footprint east of the two giant trees
(T232/T234).
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Polygon
from shapely.ops import transform as shp_transform

ROOT = Path(r"D:\CFD_Shadow")
CTX = ROOT / "data" / "buildings" / "context_1p5km.json"
PUBLIC = ROOT / "dashboard" / "public" / "buildings" / "context_1p5km.json"
WIND = ROOT / "data" / "wind" / "buildings.json"
OX, OY, OZ = 836318.0, 818150.0, 2.0


def fetch_campus_extras() -> list[dict]:
    # PolyU core + library strip
    south, west, north, east = 22.3015, 114.1770, 22.3075, 114.1835
    query = f"""[out:json][timeout:120];
(
  way["amenity"="library"]({south},{west},{north},{east});
  way["amenity"="university"]({south},{west},{north},{east});
  way["building:part"]({south},{west},{north},{east});
  relation["amenity"="library"]({south},{west},{north},{east});
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

    to_hk = Transformer.from_crs("EPSG:4326", "EPSG:2326", always_xy=True)
    out: list[dict] = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        geom = el.get("geometry") or []
        if len(geom) < 4:
            continue
        if "building" in tags and tags.get("amenity") != "library":
            # already covered by main building export (except library)
            continue
        coords = [(p["lon"], p["lat"]) for p in geom]
        poly = Polygon(coords)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.area < 1e-10:
            continue
        poly_hk = shp_transform(lambda x, y, z=None: to_hk.transform(x, y), poly)
        if poly_hk.is_empty or poly_hk.area < 40:
            continue
        ring = [
            [round(float(x) - OX, 2), round(float(y) - OY, 2)]
            for x, y in list(poly_hk.exterior.coords)[:-1]
        ]
        if len(ring) < 3:
            continue
        # Library massing from aerial / neighbouring towers — not a 1-storey slab.
        name = str(tags.get("name") or tags.get("name:en") or tags.get("amenity") or "")
        if tags.get("amenity") == "library" or "library" in name.lower() or "圖書館" in name:
            height = 28.0
        else:
            levels = tags.get("building:levels") or tags.get("levels")
            try:
                height = max(float(levels) * 3.2, 8.0) if levels else 16.0
            except ValueError:
                height = 16.0
        out.append(
            {
                "osm_id": int(el.get("id") or 0),
                "name": name,
                "height_m": round(height, 2),
                "ring": ring,
                "source": "osm_amenity_patch",
            }
        )
    return out


def landsd_gap_fillers(existing_ids: set[int]) -> list[dict]:
    """Bring LandsD footprints that sit in the library gap if still missing."""
    if not WIND.exists():
        return []
    wind = json.loads(WIND.read_text(encoding="utf-8"))
    out = []
    for b in wind.get("buildings", []):
        ring = b.get("ring") or []
        if len(ring) < 3:
            continue
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        # Gap east of T232/T234
        if not (230 <= cx <= 290 and 100 <= cy <= 175):
            continue
        oid = int(b.get("osm_id") or 0)
        # Prefer OSM library polygon; only add LandsD if no OSM cover nearby
        try:
            area = abs(Polygon(ring).area)
        except Exception:
            continue
        if area < 80:
            continue
        h = float(b.get("height_m") or 8.0)
        # DSM sometimes collapses podiums to 8 m — lift known gap masses.
        if h < 12:
            h = 22.0
        out.append(
            {
                "osm_id": oid if oid else -9000 - len(out),
                "name": str(b.get("name") or f"LandsD gap {oid}"),
                "height_m": round(h, 2),
                "ring": ring,
                "source": "landsd_gap_fill",
            }
        )
    return out


def main() -> int:
    ctx = json.loads(CTX.read_text(encoding="utf-8"))
    existing = {int(b.get("osm_id") or 0) for b in ctx.get("buildings", [])}
    extras = fetch_campus_extras()
    added = []
    for b in extras:
        oid = int(b["osm_id"])
        if oid in existing:
            # Upgrade height/name if previously missing
            for old in ctx["buildings"]:
                if int(old.get("osm_id") or 0) == oid:
                    old["height_m"] = max(float(old.get("height_m") or 0), b["height_m"])
                    if b.get("name"):
                        old["name"] = b["name"]
                    old["source"] = b.get("source")
                    added.append(("upgrade", oid, b.get("name")))
                    break
            continue
        ctx["buildings"].append(b)
        existing.add(oid)
        added.append(("add", oid, b.get("name"), b["height_m"]))

    # If library still absent, force LandsD gap fillers
    has_library = any(
        "library" in str(b.get("name") or "").lower() or "圖書館" in str(b.get("name") or "")
        for b in ctx["buildings"]
    )
    if not has_library:
        for b in landsd_gap_fillers(existing):
            ctx["buildings"].append(b)
            added.append(("landsd", b["osm_id"], b.get("name"), b["height_m"]))

    ctx["n_buildings"] = len(ctx["buildings"])
    ctx["patch_note"] = (
        "Added amenity=library / building:part masses (Pao Yue-kong Library east of T232/T234)."
    )
    CTX.write_text(json.dumps(ctx), encoding="utf-8")
    PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC.write_text(json.dumps(ctx), encoding="utf-8")
    print("n_buildings", ctx["n_buildings"])
    print("changes", added)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
