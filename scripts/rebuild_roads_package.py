"""Rebuild denser, less-broken roads/paths for the dashboard.

- LandsD 3D Pedestrian Network: keep full campus coverage, drop micro-stubs,
  chain connected segments into longer polylines.
- Vehicle roads: retry OSM; fall back to wind-package highways.
Does not touch buildings.
"""

from __future__ import annotations

import json
import math
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"D:\CFD_Shadow")
DATA = ROOT / "data" / "buildings"
PUBLIC = ROOT / "dashboard" / "public" / "buildings"
ORIGIN = (836318.0, 818150.0, 2.0)
CENTER_LAT, CENTER_LON = 22.3046, 114.1797
RADIUS_M = 1500.0
MIN_SEG_LEN_M = 1.2


def round_pt(p: list[float], nd: int = 2) -> tuple[float, float]:
    return (round(float(p[0]), nd), round(float(p[1]), nd))


def seg_length(coords: list) -> float:
    L = 0.0
    for i in range(1, len(coords)):
        dx = coords[i][0] - coords[i - 1][0]
        dy = coords[i][1] - coords[i - 1][1]
        L += math.hypot(dx, dy)
    return L


def within_radius(coords: list, r: float) -> bool:
    r2 = r * r
    return any(c[0] * c[0] + c[1] * c[1] <= r2 for c in coords)


def chain_segments(segs: list[dict]) -> list[dict]:
    """Join segments that share endpoints into longer polylines."""
    unused = []
    for i, s in enumerate(segs):
        coords = s.get("coords") or []
        if len(coords) < 2:
            continue
        unused.append(
            {
                "coords": [[float(c[0]), float(c[1])] for c in coords],
                "highway": s.get("highway") or "footway",
                "width_m": float(s.get("width_m") or 2.4),
                "name": s.get("name") or "",
                "source": s.get("source") or "landsd_pedestrian",
            }
        )

    # endpoint -> list of unused indices still alive
    alive = set(range(len(unused)))
    adj: dict[tuple[float, float], list[tuple[int, bool]]] = defaultdict(list)
    for i, s in enumerate(unused):
        a = round_pt(s["coords"][0])
        b = round_pt(s["coords"][-1])
        adj[a].append((i, True))   # True = start
        adj[b].append((i, False))  # False = end

    chains: list[dict] = []

    def take(i: int) -> dict | None:
        if i not in alive:
            return None
        alive.remove(i)
        return unused[i]

    while alive:
        i0 = next(iter(alive))
        s0 = take(i0)
        if s0 is None:
            continue
        coords = list(s0["coords"])
        hw = s0["highway"]
        width = s0["width_m"]
        name = s0["name"]
        source = s0["source"]

        # extend forward
        guard = 0
        while guard < 5000:
            guard += 1
            tip = round_pt(coords[-1])
            nxt = None
            for j, at_start in adj.get(tip, []):
                if j not in alive:
                    continue
                cand = unused[j]
                if at_start:
                    nxt = cand["coords"][1:]
                else:
                    nxt = list(reversed(cand["coords"]))[1:]
                take(j)
                break
            if not nxt:
                break
            coords.extend(nxt)

        # extend backward
        guard = 0
        while guard < 5000:
            guard += 1
            tip = round_pt(coords[0])
            prev = None
            for j, at_start in adj.get(tip, []):
                if j not in alive:
                    continue
                cand = unused[j]
                if at_start:
                    prev = list(reversed(cand["coords"]))[:-1]
                else:
                    prev = cand["coords"][:-1]
                take(j)
                break
            if not prev:
                break
            coords = prev + coords

        if len(coords) < 2 or seg_length(coords) < MIN_SEG_LEN_M:
            continue
        # light simplify: drop near-collinear midpoints
        if len(coords) > 40:
            step = max(1, len(coords) // 80)
            simplified = coords[::step]
            if simplified[-1] != coords[-1]:
                simplified.append(coords[-1])
            coords = simplified
        chains.append(
            {
                "coords": [[round(c[0], 2), round(c[1], 2)] for c in coords],
                "highway": hw,
                "width_m": width,
                "name": name,
                "source": source,
            }
        )
    return chains


def fetch_osm_highways() -> list[dict]:
    dlat = RADIUS_M / 111_320.0
    dlon = RADIUS_M / (111_320.0 * max(0.2, math.cos(math.radians(CENTER_LAT))))
    south, west = CENTER_LAT - dlat, CENTER_LON - dlon
    north, east = CENTER_LAT + dlat, CENTER_LON + dlon
    query = f"""[out:json][timeout:240];
(
  way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|service|living_street)$"]({south},{west},{north},{east});
);
out tags geom;
"""
    urls = (
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    )
    cache = DATA / "osm_highways_1p5km.json"
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
    else:
        data = None
        last = None
        for url in urls:
            try:
                print(f"  Overpass {url} …", flush=True)
                req = urllib.request.Request(
                    url,
                    data=query.encode("utf-8"),
                    headers={"User-Agent": "cfd-shadow/0.4"},
                )
                with urllib.request.urlopen(req, timeout=300) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                cache.write_text(json.dumps(data), encoding="utf-8")
                break
            except Exception as exc:  # noqa: BLE001
                last = exc
                print(f"  fail: {exc}", flush=True)
        if data is None:
            print(f"OSM highways unavailable ({last})", flush=True)
            return []

    try:
        from pyproj import Transformer
    except ImportError:
        print("pyproj missing — skip OSM", flush=True)
        return []

    to_hk = Transformer.from_crs("EPSG:4326", "EPSG:2326", always_xy=True)
    ox, oy, _ = ORIGIN
    out = []
    for el in data.get("elements") or []:
        geom = el.get("geometry") or []
        tags = el.get("tags") or {}
        if len(geom) < 2:
            continue
        line = []
        for p in geom:
            x, y = to_hk.transform(p["lon"], p["lat"])
            line.append([round(float(x) - ox, 2), round(float(y) - oy, 2)])
        if len(line) < 2 or not within_radius(line, RADIUS_M + 80):
            continue
        hw = tags.get("highway") or "service"
        width = 8.0 if hw in ("trunk", "primary", "motorway") else 5.5 if hw in ("secondary", "tertiary") else 4.0
        out.append(
            {
                "coords": line,
                "highway": hw,
                "width_m": width,
                "name": str(tags.get("name") or tags.get("name:en") or ""),
                "source": "osm",
            }
        )
    print(f"OSM vehicle ways: {len(out)}", flush=True)
    return out


def wind_vehicle_fallback() -> list[dict]:
    wr = ROOT / "dashboard" / "public" / "wind" / "roads.json"
    if not wr.exists():
        return []
    data = json.loads(wr.read_text(encoding="utf-8"))
    out = []
    skip = {"footway", "path", "steps", "pedestrian", "cycleway", "track"}
    for s in data.get("segments") or []:
        hw = str(s.get("highway") or "")
        if hw in skip:
            continue
        coords = s.get("coords") or []
        if len(coords) < 2:
            continue
        out.append(
            {
                "coords": coords,
                "highway": hw,
                "width_m": float(s.get("width_m") or 5.0),
                "name": s.get("name") or "",
                "source": "wind_fallback",
            }
        )
    return out


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)

    ped_path = DATA / "pedestrian_1p5km.json"
    if not ped_path.exists():
        raise SystemExit("Missing pedestrian_1p5km.json — run export_pedestrian_network.py first")
    ped = json.loads(ped_path.read_text(encoding="utf-8"))
    raw_segs = [
        s
        for s in (ped.get("segments") or [])
        if within_radius(s.get("coords") or [], RADIUS_M + 50)
        and seg_length(s.get("coords") or []) >= MIN_SEG_LEN_M
    ]
    print(f"Ped raw in radius: {len(raw_segs)} / {len(ped.get('segments') or [])}", flush=True)
    ped_chains = chain_segments(raw_segs)
    print(f"Ped chained polylines: {len(ped_chains)}", flush=True)

    vehicle = fetch_osm_highways()
    if not vehicle:
        vehicle = wind_vehicle_fallback()
        print(f"Using wind vehicle fallback: {len(vehicle)}", flush=True)

    roads = vehicle + ped_chains
    payload = {
        "version": 3,
        "style_rev": 8,
        "crs": "local_metres_from_domain_origin",
        "origin_hk80": list(ORIGIN),
        "radius_m": RADIUS_M,
        "n_segments": len(roads),
        "n_vehicle": len(vehicle),
        "n_pedestrian": len(ped_chains),
        "segments": roads,
        "source": "OSM/wind vehicle + LandsD 3D Pedestrian Network (chained)",
        "map_ref": "https://3d.map.gov.hk/",
        "note": "Chained ped polylines; no building changes.",
    }
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    (DATA / "roads_1p5km.json").write_text(text, encoding="utf-8")
    (PUBLIC / "roads_1p5km.json").write_text(text, encoding="utf-8")
    print(
        f"Wrote {len(vehicle)} vehicle + {len(ped_chains)} ped -> "
        f"{(PUBLIC / 'roads_1p5km.json').stat().st_size / 1e6:.2f} MB",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
