"""Export PolyU segmented LAZ crowns to a browser-ready point package.

Reads:
  Z:\\Carbon Neutrality\\Segmented Individual Trees\\RTK_T*.laz|las
  D:\\CFD_Shadow\\data\\trees\\trees_campus_all.csv

Writes:
  D:\\CFD_Shadow\\data\\trees\\crowns.meta.json
  D:\\CFD_Shadow\\data\\trees\\crowns.bin
  (+ copies into dashboard/public/trees/)
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from pathlib import Path

import laspy
import numpy as np

ROOT = Path(r"D:\CFD_Shadow")
LAZ_DIR = Path(r"Z:\Carbon Neutrality\Segmented Individual Trees")
CATALOG = ROOT / "data" / "trees" / "trees_campus_all.csv"
OUT_DIR = ROOT / "data" / "trees"
PUBLIC_DIR = ROOT / "dashboard" / "public" / "trees"
# Same origin as wind package so layers line up.
DEFAULT_ORIGIN = (836318.0, 818150.0, 2.0)


def voxel_downsample(xyz: np.ndarray, voxel_m: float, max_points: int, rng: np.random.Generator) -> np.ndarray:
    if xyz.shape[0] == 0:
        return xyz
    mins = xyz.min(axis=0)
    keys = np.floor((xyz - mins) / voxel_m).astype(np.int64)
    # Pack 3D voxel index into one int64 key
    span = keys.max(axis=0) - keys.min(axis=0) + 1
    packed = keys[:, 0] + keys[:, 1] * (span[0] + 1) + keys[:, 2] * (span[0] + 1) * (span[1] + 1)
    _, idx = np.unique(packed, return_index=True)
    out = xyz[idx]
    if out.shape[0] > max_points:
        choose = rng.choice(out.shape[0], size=max_points, replace=False)
        out = out[choose]
    return out


def parse_tree_id(name: str) -> int | None:
    m = re.search(r"RTK_T(\d+)", name, re.I)
    return int(m.group(1)) if m else None


def load_catalog(path: Path) -> dict[int, dict]:
    by_id: dict[int, dict] = {}
    if not path.exists():
        return by_id
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            tid = row.get("tree_id") or ""
            m = re.search(r"(\d+)", tid)
            if not m:
                continue
            i = int(m.group(1))
            by_id[i] = row
    return by_id


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--laz-dir", type=Path, default=LAZ_DIR)
    ap.add_argument("--voxel-m", type=float, default=0.25)
    ap.add_argument("--max-points", type=int, default=1200)
    ap.add_argument("--limit", type=int, default=0, help="Optional cap for smoke tests")
    ap.add_argument("--origin", type=float, nargs=3, default=list(DEFAULT_ORIGIN))
    args = ap.parse_args()

    laz_dir: Path = args.laz_dir
    if not laz_dir.exists():
        print(f"LAZ dir missing: {laz_dir}", file=sys.stderr)
        return 1

    files = sorted(
        [p for p in laz_dir.iterdir() if p.suffix.lower() in {".laz", ".las"} and p.name.upper().startswith("RTK_T")],
        key=lambda p: (parse_tree_id(p.name) or 0, p.suffix),
    )
    # Prefer .laz over .las when both exist for same id
    by_id_files: dict[int, Path] = {}
    for p in files:
        tid = parse_tree_id(p.name)
        if tid is None:
            continue
        prev = by_id_files.get(tid)
        if prev is None or (prev.suffix.lower() == ".las" and p.suffix.lower() == ".laz"):
            by_id_files[tid] = p

    ids = sorted(by_id_files)
    if args.limit > 0:
        ids = ids[: args.limit]

    catalog = load_catalog(CATALOG)
    ox, oy, oz = map(float, args.origin)
    rng = np.random.default_rng(42)

    chunks: list[np.ndarray] = []
    trees_meta: list[dict] = []
    offset = 0
    failed: list[str] = []

    print(f"Exporting {len(ids)} trees from {laz_dir}")
    print(f"voxel={args.voxel_m}m max_points={args.max_points} origin=({ox},{oy},{oz})")

    for i, tid in enumerate(ids, 1):
        path = by_id_files[tid]
        try:
            las = laspy.read(str(path))
            xyz = np.column_stack((np.asarray(las.x), np.asarray(las.y), np.asarray(las.z))).astype(np.float64)
            finite = np.isfinite(xyz).all(axis=1)
            xyz = xyz[finite]
            if xyz.shape[0] < 8:
                failed.append(f"{path.name}: too few points")
                continue

            cat = catalog.get(tid, {})
            # Reject clouds that are not in HK1980 campus space (some .las are corrupt CRS).
            cx_abs = float(np.median(xyz[:, 0]))
            cy_abs = float(np.median(xyz[:, 1]))
            if not (835800.0 <= cx_abs <= 837400.0 and 817700.0 <= cy_abs <= 819200.0):
                # If inventory XY exists, still skip bad cloud (attrs-only later).
                failed.append(
                    f"{path.name}: out-of-campus CRS median=({cx_abs:.1f},{cy_abs:.1f})"
                )
                continue
            if cat.get("easting") and cat.get("northing"):
                try:
                    cat_e = float(cat["easting"])
                    cat_n = float(cat["northing"])
                    if abs(cx_abs - cat_e) > 80.0 or abs(cy_abs - cat_n) > 80.0:
                        failed.append(
                            f"{path.name}: far from catalog XY "
                            f"cloud=({cx_abs:.1f},{cy_abs:.1f}) cat=({cat_e:.1f},{cat_n:.1f})"
                        )
                        continue
                except ValueError:
                    pass

            raw_n = int(xyz.shape[0])
            ds = voxel_downsample(xyz, args.voxel_m, args.max_points, rng)
            local = np.empty_like(ds, dtype=np.float32)
            local[:, 0] = (ds[:, 0] - ox).astype(np.float32)
            local[:, 1] = (ds[:, 1] - oy).astype(np.float32)
            local[:, 2] = (ds[:, 2] - oz).astype(np.float32)

            z_min = float(local[:, 2].min())
            z_max = float(local[:, 2].max())
            trees_meta.append(
                {
                    "tree_id": tid,
                    "file": path.name,
                    "offset": offset,
                    "count": int(local.shape[0]),
                    "raw_points": raw_n,
                    "z_min": round(z_min, 3),
                    "z_max": round(z_max, 3),
                    "height_span_m": round(z_max - z_min, 3),
                    "height_m_inv": float(cat.get("height_m") or 0) or None,
                    "crown_spread_m": float(cat.get("crown_spread_m") or 0) or None,
                    "species": cat.get("species") or None,
                    "cx": round(float(local[:, 0].mean()), 3),
                    "cy": round(float(local[:, 1].mean()), 3),
                }
            )
            chunks.append(local)
            offset += int(local.shape[0])
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{path.name}: {exc}")

        if i % 25 == 0 or i == len(ids):
            print(f"  [{i}/{len(ids)}] points_so_far={offset} failed={len(failed)}")

    if not chunks:
        print("No crowns exported.", file=sys.stderr)
        return 1

    xyz_all = np.vstack(chunks).astype(np.float32, copy=False)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

    bin_path = OUT_DIR / "crowns.bin"
    meta_path = OUT_DIR / "crowns.meta.json"
    xyz_all.tofile(bin_path)

    meta = {
        "version": 1,
        "crs": "EPSG:2326 local metres from origin_hk80",
        "origin_hk80": [ox, oy, oz],
        "encoding": "float32_xyz",
        "order": "tree-major contiguous xyz",
        "axes": "x=east_m, y=north_m, z=up_m (local)",
        "voxel_m": args.voxel_m,
        "max_points_per_tree": args.max_points,
        "n_trees": len(trees_meta),
        "n_points": int(xyz_all.shape[0]),
        "bytes": int(bin_path.stat().st_size),
        "source_dir": str(laz_dir),
        "failed": failed[:50],
        "n_failed": len(failed),
        "trees": trees_meta,
        "note": "Original segmented LiDAR crowns (downsampled). Use for real tree shape; shadow later.",
    }
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    shutil.copy2(bin_path, PUBLIC_DIR / "crowns.bin")
    shutil.copy2(meta_path, PUBLIC_DIR / "crowns.meta.json")

    print(
        f"Wrote {meta['n_trees']} trees / {meta['n_points']} points "
        f"({meta['bytes']/1e6:.1f} MB) -> {bin_path}"
    )
    if failed:
        print(f"Failed {len(failed)} files (first): {failed[:5]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
