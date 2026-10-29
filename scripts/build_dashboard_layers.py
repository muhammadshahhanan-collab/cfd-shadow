"""Merge LandsD buildings + OSM roads + ped network into viewer-ready packages.

Writes:
  dashboard/public/buildings/context_1p5km.json
  dashboard/public/buildings/roads_1p5km.json
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\CFD_Shadow")
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data" / "buildings"
PUBLIC = ROOT / "dashboard" / "public" / "buildings"
ORIGIN = [836318.0, 818150.0, 2.0]


def run(script: str, *, required: bool = True) -> bool:
    print(f"\n=== {script} ===", flush=True)
    r = subprocess.run([sys.executable, "-u", str(SCRIPTS / script)], cwd=str(SCRIPTS))
    if r.returncode != 0:
        if required:
            raise SystemExit(f"{script} failed with {r.returncode}")
        print(f"WARN: {script} failed with {r.returncode} — continuing")
        return False
    return True


def osm_roads_to_segments(roads: list[dict]) -> list[dict]:
    segs = []
    for r in roads:
        line = r.get("line") or r.get("coords") or []
        if len(line) < 2:
            continue
        hw = str(r.get("highway") or r.get("kind") or "service")
        width = 6.0
        if hw in ("footway", "path", "steps", "pedestrian", "cycleway", "track"):
            width = 2.2
        elif hw in ("residential", "service", "tertiary"):
            width = 4.5
        elif hw in ("primary", "trunk", "secondary"):
            width = 8.0
        segs.append(
            {
                "coords": line,
                "highway": hw,
                "width_m": width,
                "name": r.get("name") or "",
                "source": "osm",
            }
        )
    return segs


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)

    # 1) OSM for road/rail carriageways (cached after first fetch)
    osm_ok = run("export_context_buildings.py", required=False)
    # 2) LandsD buildings (reuses OSM roads from context file when possible)
    run("export_landsd_buildings.py")
    # 3) Pedestrian network
    ped_ok = run("export_pedestrian_network.py", required=False)

    ctx = json.loads((DATA / "context_1p5km.json").read_text(encoding="utf-8"))
    ped = (
        json.loads((DATA / "pedestrian_1p5km.json").read_text(encoding="utf-8"))
        if ped_ok and (DATA / "pedestrian_1p5km.json").exists()
        else {"segments": []}
    )

    buildings = ctx.get("buildings") or []
    osm_segs = osm_roads_to_segments(ctx.get("roads") or [])
    # Keep OSM vehicle roads; drop OSM footways if LandsD ped covers them better
    vehicle = [
        s
        for s in osm_segs
        if s["highway"]
        not in {"footway", "path", "steps", "pedestrian", "cycleway", "track"}
    ]
    if not vehicle:
        # Fallback: CFD wind package roads (smaller domain) so viewer is not empty
        wind_roads = ROOT / "dashboard" / "public" / "wind" / "roads.json"
        if wind_roads.exists():
            wr = json.loads(wind_roads.read_text(encoding="utf-8"))
            for s in wr.get("segments") or []:
                vehicle.append({**s, "source": s.get("source") or "wind_fallback"})
            print(f"Using wind-package roads fallback ({len(vehicle)} segs)")
    ped_segs = ped.get("segments") or []
    roads = vehicle + ped_segs
    print(f"osm_ok={osm_ok} ped_ok={ped_ok}", flush=True)

    buildings_payload = {
        "version": 4,
        "style_rev": 4,
        "crs": "local_metres_from_domain_origin",
        "origin_hk80": ORIGIN,
        "radius_m": ctx.get("radius_m") or 1500,
        "source": ctx.get("source"),
        "map_ref": "https://3d.map.gov.hk/",
        "n_buildings": len(buildings),
        "buildings": buildings,
        "note": "LandsD Tower+Podium footprints extruded by Top-Base height (~1.5 km).",
    }
    roads_payload = {
        "version": 2,
        "style_rev": 6,
        "crs": "local_metres_from_domain_origin",
        "origin_hk80": ORIGIN,
        "radius_m": 1500,
        "n_segments": len(roads),
        "n_vehicle": len(vehicle),
        "n_pedestrian": len(ped_segs),
        "segments": roads,
        "source": "OSM highways + LandsD 3D Pedestrian Network",
        "map_ref": "https://3d.map.gov.hk/",
    }

    b_text = json.dumps(buildings_payload, ensure_ascii=False, separators=(",", ":"))
    r_text = json.dumps(roads_payload, ensure_ascii=False, separators=(",", ":"))
    (DATA / "context_buildings_viewer.json").write_text(b_text, encoding="utf-8")
    (DATA / "roads_1p5km.json").write_text(r_text, encoding="utf-8")
    (PUBLIC / "context_1p5km.json").write_text(b_text, encoding="utf-8")
    (PUBLIC / "roads_1p5km.json").write_text(r_text, encoding="utf-8")
    # Keep a combined copy for convenience
    (PUBLIC / "context_full_1p5km.json").write_text(
        json.dumps(
            {
                **buildings_payload,
                "n_roads": len(roads),
                "roads": roads,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    print(
        f"\nDashboard layers: {len(buildings)} buildings, "
        f"{len(vehicle)} vehicle roads, {len(ped_segs)} ped segments"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
