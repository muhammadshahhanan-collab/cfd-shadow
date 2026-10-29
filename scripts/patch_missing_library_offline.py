"""Offline patch: add LandsD gap footprints + library outline from wind package.

Used when Overpass is unavailable. Targets the empty mass east of trees T232/T234.
"""

from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import Polygon

ROOT = Path(r"D:\CFD_Shadow")
CTX = ROOT / "data" / "buildings" / "context_1p5km.json"
PUBLIC = ROOT / "dashboard" / "public" / "buildings" / "context_1p5km.json"
WIND = ROOT / "data" / "wind" / "buildings.json"


def covers_point(buildings: list[dict], x: float, y: float, tol: float = 8.0) -> bool:
    p_hits = 0
    for b in buildings:
        ring = b.get("ring") or []
        if len(ring) < 3:
            continue
        try:
            poly = Polygon(ring)
        except Exception:
            continue
        if poly.is_empty:
            continue
        if poly.buffer(tol).contains(Polygon([(x, y), (x + 0.1, y), (x, y + 0.1)]).centroid):
            # rough: distance to polygon
            pass
        if poly.distance(Polygon([(x, y)]).centroid if False else __import__("shapely.geometry", fromlist=["Point"]).Point(x, y)) <= tol:
            # Only count real extrusions tall enough to read as the missing block
            if float(b.get("height_m") or 0) >= 12:
                p_hits += 1
    return p_hits > 0


def main() -> int:
    from shapely.geometry import Point

    ctx = json.loads(CTX.read_text(encoding="utf-8"))
    wind = json.loads(WIND.read_text(encoding="utf-8"))
    existing_ids = {int(b.get("osm_id") or 0) for b in ctx["buildings"]}

    # Known gap centroid (east of T232/T234) from earlier Overpass probe of the library
    gap_x, gap_y = 260.0, 130.0
    added = []

    # Prefer LandsD footprints in the library strip; lift collapsed 8 m DSM slabs.
    for b in wind.get("buildings", []):
        ring = b.get("ring") or []
        if len(ring) < 3:
            continue
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        if not (230 <= cx <= 295 and 95 <= cy <= 180):
            continue
        try:
            area = abs(Polygon(ring).area)
        except Exception:
            continue
        if area < 100:
            continue
        oid = int(b.get("osm_id") or 0)
        # Avoid dup if we already have a tall OSM building covering the centroid
        already = False
        for old in ctx["buildings"]:
            oring = old.get("ring") or []
            if len(oring) < 3:
                continue
            try:
                op = Polygon(oring)
            except Exception:
                continue
            if op.is_empty:
                continue
            if op.distance(Point(cx, cy)) < 5 and float(old.get("height_m") or 0) >= 18:
                already = True
                break
        if already:
            continue
        h = float(b.get("height_m") or 8.0)
        name = str(b.get("name") or f"LandsD-{abs(oid)}")
        # Library / podium strip east of the two big trees — make mass readable
        if h < 18:
            h = 26.0 if 240 <= cx <= 280 and 105 <= cy <= 160 else 18.0
            if 245 <= cx <= 270 and 120 <= cy <= 155:
                name = "Pao Yue-kong Library (LandsD)"
                h = 28.0
        if oid in existing_ids:
            # replace short twin if present
            for old in ctx["buildings"]:
                if int(old.get("osm_id") or 0) == oid:
                    if float(old.get("height_m") or 0) < h:
                        old["height_m"] = h
                        old["name"] = name
                        old["source"] = "landsd_gap_fill"
                        added.append(("upgrade", oid, name, h))
                    break
            continue
        ctx["buildings"].append(
            {
                "osm_id": oid,
                "name": name,
                "height_m": round(h, 2),
                "ring": ring,
                "source": "landsd_gap_fill",
            }
        )
        existing_ids.add(oid)
        added.append(("add", oid, name, h, round(cx, 1), round(cy, 1), round(area, 1)))

    # If still no cover at library centroid, synthesize a coarse trapezoid from LandsD-21 hull
    if not any(
        "library" in str(b.get("name") or "").lower() or "圖書館" in str(b.get("name") or "")
        for b in ctx["buildings"]
    ):
        # Merge LandsD-19/21/23 convex-ish outline by taking their union bbox ring as fallback
        parts = []
        for b in wind.get("buildings", []):
            if int(b.get("osm_id") or 0) in (-19, -21, -23):
                parts.append(Polygon(b["ring"]))
        if parts:
            from shapely.ops import unary_union

            u = unary_union(parts)
            if not u.is_empty:
                # simplify for viewer
                simp = u.simplify(1.0)
                if simp.geom_type == "Polygon":
                    ring = [
                        [round(float(x), 2), round(float(y), 2)]
                        for x, y in list(simp.exterior.coords)[:-1]
                    ]
                    ctx["buildings"].append(
                        {
                            "osm_id": -184551440,
                            "name": "Pao Yue-kong Library (LandsD union)",
                            "height_m": 28.0,
                            "ring": ring,
                            "source": "landsd_gap_fill",
                        }
                    )
                    added.append(("union", -184551440, len(ring), round(simp.area, 1)))

    ctx["n_buildings"] = len(ctx["buildings"])
    ctx["patch_note"] = (
        "Filled missing mass east of T232/T234 (Pao Yue-kong Library zone) from LandsD footprints."
    )
    text = json.dumps(ctx)
    CTX.write_text(text, encoding="utf-8")
    PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC.write_text(text, encoding="utf-8")
    print("n_buildings", ctx["n_buildings"])
    print("added", added)

    # Verify cover at gap
    covered = False
    for b in ctx["buildings"]:
        ring = b.get("ring") or []
        if len(ring) < 3:
            continue
        try:
            poly = Polygon(ring)
        except Exception:
            continue
        if poly.distance(Point(gap_x, gap_y)) < 15 and float(b.get("height_m") or 0) >= 18:
            covered = True
            print("cover", b.get("osm_id"), b.get("name"), b.get("height_m"), "dist", round(poly.distance(Point(gap_x, gap_y)), 2))
    print("gap_covered", covered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
