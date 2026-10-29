"""Export LandsD 3D Pedestrian Network segments ~1.5 km around PolyU.

Tries CSDI MapServer / FeatureServer query; writes viewer-ready road segments.
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(r"D:\CFD_Shadow")
OUT = ROOT / "data" / "buildings"
PUBLIC = ROOT / "dashboard" / "public" / "buildings"
ORIGIN = (836318.0, 818150.0, 2.0)
CENTER_LAT, CENTER_LON = 22.3046, 114.1797
RADIUS_M = 1500.0
CACHE = OUT / "pedestrian_raw_1p5km.geojson"

# Common CSDI service id for 3D Pedestrian Network
SERVICE_CANDIDATES = [
    "https://portal.csdi.gov.hk/server/rest/services/common/landsd_rcd_1637222018065_52265/MapServer",
    "https://portal.csdi.gov.hk/server/rest/services/common/landsd_rcd_1637222018065_52265/FeatureServer",
]

# featuretype codes often used in ped network (1=footway etc.) — keep as labels when present
TYPE_HINT = {
    "1": "footway",
    "2": "footbridge",
    "6": "traffic_island",
    "32": "crossing",
}


def bbox_wgs84(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(0.2, math.cos(math.radians(lat))))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat  # xmin,ymin,xmax,ymax WGS84


def discover_layer(base: str) -> str | None:
    url = base.rstrip("/") + "?f=pjson"
    req = urllib.request.Request(url, headers={"User-Agent": "cfd-shadow/0.3"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        meta = json.loads(resp.read().decode("utf-8"))
    layers = meta.get("layers") or []
    for lyr in layers:
        name = str(lyr.get("name") or "").lower()
        if "pedestrianroute" in name.replace(" ", "") or name == "pedestrian route":
            return f"{base.rstrip('/')}/{lyr['id']}/query"
    # fallback first layer
    if layers:
        return f"{base.rstrip('/')}/{layers[0]['id']}/query"
    return None


def fetch_geojson(query_url: str, cache: Path) -> list[dict]:
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        feats = data.get("features") or []
        if feats:
            print(f"  Using cached ped network ({len(feats)} features)")
            return feats

    ox, oy, _ = ORIGIN
    # Prefer HK1980 envelope when service supports 2326
    xmin, ymin, xmax, ymax = ox - RADIUS_M, oy - RADIUS_M, ox + RADIUS_M, oy + RADIUS_M
    all_feats: list[dict] = []
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "geometry": f"{xmin},{ymin},{xmax},{ymax}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "2326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "2326",
            "f": "geojson",
            "resultRecordCount": "2000",
            "resultOffset": str(offset),
        }
        url = query_url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "cfd-shadow/0.3"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("error"):
            raise RuntimeError(data["error"])
        feats = data.get("features") or []
        print(f"  ped page offset={offset} n={len(feats)}")
        all_feats.extend(feats)
        if not feats or not data.get("exceededTransferLimit"):
            break
        offset += len(feats)
        if offset > 80000:
            break

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({"type": "FeatureCollection", "features": all_feats}, ensure_ascii=False),
        encoding="utf-8",
    )
    return all_feats


def to_segments(feats: list[dict]) -> list[dict]:
    ox, oy, oz = ORIGIN
    segs: list[dict] = []
    for f in feats:
        geom = f.get("geometry") or {}
        props = f.get("properties") or {}
        gtype = geom.get("type")
        coords_raw = geom.get("coordinates")
        if not coords_raw:
            continue
        lines = []
        if gtype == "LineString":
            lines = [coords_raw]
        elif gtype == "MultiLineString":
            lines = coords_raw
        else:
            continue
        ftype = str(props.get("featuretype") or props.get("FEATURETYPE") or "")
        alias = str(
            props.get("aliasnameen")
            or props.get("ALIASNAMEEN")
            or props.get("streetnameen")
            or props.get("STREETNAMEEN")
            or ""
        )
        highway = TYPE_HINT.get(ftype, "footway")
        if "bridge" in alias.lower() or highway == "footbridge":
            highway = "footway"
        if "crossing" in alias.lower() or highway == "crossing":
            highway = "footway"
        for line in lines:
            coords = []
            for pt in line:
                if len(pt) < 2:
                    continue
                x, y = float(pt[0]), float(pt[1])
                # If still lon/lat, skip (expect 2326)
                if abs(x) < 180 and abs(y) < 90:
                    continue
                coords.append([round(x - ox, 2), round(y - oy, 2)])
            if len(coords) < 2:
                continue
            # Drop segments far outside radius pad
            if all(abs(c[0]) > RADIUS_M + 50 or abs(c[1]) > RADIUS_M + 50 for c in coords):
                continue
            segs.append(
                {
                    "coords": coords,
                    "highway": highway,
                    "width_m": 2.4 if highway == "footway" else 3.0,
                    "name": alias,
                    "source": "landsd_pedestrian",
                    "z0": round(float(line[0][2]) - oz, 2) if len(line[0]) > 2 else 0.0,
                }
            )
    return segs


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    query_url = None
    last_err = None
    for base in SERVICE_CANDIDATES:
        try:
            print(f"Discover {base}")
            query_url = discover_layer(base)
            if query_url:
                print(f"  layer query: {query_url}")
                break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"  fail: {exc}")
    if not query_url:
        raise SystemExit(f"Could not discover pedestrian layer: {last_err}")

    feats = fetch_geojson(query_url, CACHE)
    segs = to_segments(feats)
    payload = {
        "version": 1,
        "style_rev": 6,
        "crs": "local_metres_from_domain_origin",
        "origin_hk80": list(ORIGIN),
        "radius_m": RADIUS_M,
        "center_wgs84": [CENTER_LON, CENTER_LAT],
        "source": "LandsD 3D Pedestrian Network (CSDI)",
        "map_ref": "https://3d.map.gov.hk/",
        "n_segments": len(segs),
        "segments": segs,
    }
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    (OUT / "pedestrian_1p5km.json").write_text(text, encoding="utf-8")
    (PUBLIC / "pedestrian_1p5km.json").write_text(text, encoding="utf-8")
    print(f"Wrote {len(segs)} pedestrian segments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
