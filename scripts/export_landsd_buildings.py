"""Export LandsD Building footprints (3d.map.gov.hk / CSDI) for ~1.5 km around PolyU.

Source: Lands Department Building layer via CSDI ArcGIS REST.
Keeps Tower + Podium only (no Temporary / Open-sided shelters that look like poles).
Roads/paths come from existing OSM context (highways + footways).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

from shapely.geometry import Polygon, shape

ROOT = Path(r"D:\CFD_Shadow")
OUT = ROOT / "data" / "buildings"
PUBLIC = ROOT / "dashboard" / "public" / "buildings"
ORIGIN = (836318.0, 818150.0, 2.0)
CENTER_LAT, CENTER_LON = 22.3046, 114.1797
RADIUS_M = 1500.0
GROUND_REF_M = 5.0
MIN_AREA_M2 = 40.0
MIN_HEIGHT_M = 5.0
KEEP_TYPES = {"Tower", "Podium"}
CTX_EXISTING = OUT / "context_1p5km.json"
CACHE = OUT / "landsd_buildings_raw_1p5km.geojson"
ARC_LAYER = (
    "https://portal.csdi.gov.hk/server/rest/services/common/"
    "landsd_rcd_1637211194312_35158/MapServer/0/query"
)


def fetch_landsd(ox: float, oy: float, radius: float, cache: Path) -> list[dict]:
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        feats = data.get("features") or []
        if feats:
            print(f"  Using cached LandsD raw ({len(feats)} features)")
            return feats

    all_feats: list[dict] = []
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "geometry": f"{ox - radius},{oy - radius},{ox + radius},{oy + radius}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "2326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": (
                "OBJECTID,BuildingNameEN,BuildingNameTC,TopHeight,BaseHeight,"
                "BuildingBlockType,Shape_Area,Storeys,Status,BuildingID,GeoRefNo"
            ),
            "returnGeometry": "true",
            "outSR": "2326",
            "f": "geojson",
            "resultRecordCount": "2000",
            "resultOffset": str(offset),
        }
        url = ARC_LAYER + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "cfd-shadow/0.3 (research)"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        feats = data.get("features") or []
        print(f"  LandsD page offset={offset} n={len(feats)}")
        all_feats.extend(feats)
        if not feats or not data.get("exceededTransferLimit"):
            break
        offset += len(feats)
        if offset > 40000:
            break

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({"type": "FeatureCollection", "features": all_feats}, ensure_ascii=False),
        encoding="utf-8",
    )
    return all_feats


def ring_from_geom(geom: dict, ox: float, oy: float) -> list[list[float]] | None:
    try:
        g = shape(geom)
    except Exception:
        return None
    if g.is_empty:
        return None
    if g.geom_type == "MultiPolygon":
        g = max(g.geoms, key=lambda p: p.area)
    if g.geom_type != "Polygon":
        return None
    if not g.is_valid:
        g = g.buffer(0)
    if g.is_empty or g.area < MIN_AREA_M2:
        return None
    g = g.simplify(0.6, preserve_topology=True)
    if g.geom_type != "Polygon" or g.is_empty:
        return None
    coords = list(g.exterior.coords)[:-1]
    if len(coords) < 3:
        return None
    return [[round(float(x) - ox, 2), round(float(y) - oy, 2)] for x, y in coords]


def ensure_osm_roads() -> list[dict]:
    """Roads/paths from OSM context; regenerate from cache if missing."""
    if CTX_EXISTING.exists():
        old = json.loads(CTX_EXISTING.read_text(encoding="utf-8"))
        roads = old.get("roads") or []
        if roads and not str(old.get("source") or "").startswith("LandsD"):
            return roads
        if roads:
            return roads
    # Rebuild OSM package for roads only
    from export_context_buildings import main as osm_main

    osm_main()
    old = json.loads(CTX_EXISTING.read_text(encoding="utf-8"))
    return old.get("roads") or []


def main() -> int:
    ox, oy, _oz = ORIGIN
    print(f"LandsD Building within {RADIUS_M:.0f} m of PolyU...")
    feats = fetch_landsd(ox, oy, RADIUS_M, CACHE)
    print(f"Raw features: {len(feats)}")

    buildings: list[dict] = []
    skipped = {"type": 0, "area": 0, "height": 0, "geom": 0, "status": 0}
    for f in feats:
        p = f.get("properties") or {}
        btype = str(p.get("BuildingBlockType") or "")
        if btype not in KEEP_TYPES:
            skipped["type"] += 1
            continue
        status = str(p.get("Status") or "Active")
        if status and status.lower() not in ("active", "none", ""):
            skipped["status"] += 1
            continue
        area = float(p.get("Shape_Area") or 0.0)
        if area < MIN_AREA_M2:
            skipped["area"] += 1
            continue
        try:
            top = float(p.get("TopHeight"))
            base = float(p.get("BaseHeight"))
        except (TypeError, ValueError):
            skipped["height"] += 1
            continue
        height = top - base
        if height < MIN_HEIGHT_M:
            try:
                height = max(height, float(p.get("Storeys") or 0) * 3.0)
            except (TypeError, ValueError):
                pass
        if height < MIN_HEIGHT_M:
            skipped["height"] += 1
            continue
        ring = ring_from_geom(f.get("geometry") or {}, ox, oy)
        if not ring:
            skipped["geom"] += 1
            continue
        elev = max(0.0, base - GROUND_REF_M)
        name_en = (p.get("BuildingNameEN") or "").strip()
        name_tc = (p.get("BuildingNameTC") or "").strip()
        name = " ".join(x for x in (name_tc, name_en) if x).strip() or f"LandsD-{p.get('BuildingID')}"
        bid = int(p.get("BuildingID") or p.get("OBJECTID") or 0)
        buildings.append(
            {
                "osm_id": -abs(bid) if bid else -(len(buildings) + 1),
                "landsd_id": bid,
                "name": name,
                "height_m": round(height, 2),
                "base_m": round(elev, 2),
                "top_hkpd_m": round(top, 2),
                "block_type": btype,
                "area_m2": round(area, 1),
                "ring": ring,
                "source": "landsd_building",
            }
        )

    def named_score(b: dict) -> float:
        n = str(b.get("name") or "")
        bonus = (
            50.0
            if any(
                k in n
                for k in ("Polytechnic", "理工", "Block Z", "Z座", "Pao Yue", "包玉剛", "Innovation", "創新")
            )
            else 0.0
        )
        return b["area_m2"] * b["height_m"] + bonus * 1e4

    buildings.sort(key=named_score, reverse=True)
    kept: list[dict] = []
    kept_meta: list[tuple[Polygon, float, str]] = []
    for b in buildings:
        poly = Polygon(b["ring"])
        if not poly.is_valid or poly.is_empty:
            continue
        elev = float(b.get("base_m") or 0.0)
        btype = str(b.get("block_type") or "")
        dup = False
        for kp, ke, kt in kept_meta:
            if abs(elev - ke) > 2.5 or (btype and kt and btype != kt):
                continue
            inter = poly.intersection(kp).area
            if inter > 0.72 * min(poly.area, kp.area):
                dup = True
                break
        if dup:
            continue
        kept.append(b)
        kept_meta.append((poly, elev, btype))

    # Prefer OSM roads if already exported; never block LandsD buildings on Overpass.
    roads: list[dict] = []
    if CTX_EXISTING.exists():
        prev = json.loads(CTX_EXISTING.read_text(encoding="utf-8"))
        roads = prev.get("roads") or []
    if not roads:
        print("No OSM roads yet — writing LandsD buildings with empty roads list")

    payload = {
        "version": 3,
        "crs": "local_metres_from_domain_origin",
        "origin_hk80": list(ORIGIN),
        "radius_m": RADIUS_M,
        "center_wgs84": [CENTER_LON, CENTER_LAT],
        "source": "LandsD Building (CSDI / 3d.map.gov.hk) + OSM roads/paths",
        "map_ref": "https://3d.map.gov.hk/",
        "filter_note": (
            "Tower+Podium only; excluded Temporary/Open-sided; "
            f"min area {MIN_AREA_M2} m², min height {MIN_HEIGHT_M} m"
        ),
        "n_buildings": len(kept),
        "n_roads": len(roads),
        "skipped": skipped,
        "buildings": kept,
        "roads": roads,
    }
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    OUT.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    (OUT / "context_1p5km.json").write_text(text, encoding="utf-8")
    (PUBLIC / "context_1p5km.json").write_text(text, encoding="utf-8")
    print(f"Wrote {len(kept)} LandsD buildings + {len(roads)} roads/paths")
    print("skipped", skipped)
    for key in ("Block Z", "Pao Yue", "Innovation", "Li Ka Shing Tower"):
        hits = [b["name"] for b in kept if key.lower() in b["name"].lower()]
        sample = (hits[:1] or [""])[0][:60].encode("ascii", "replace").decode("ascii")
        print(f"  {key}: {len(hits)} {sample}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
