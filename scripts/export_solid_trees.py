"""Build solid trunk+crown meshes from LAZ crowns.

Large trees (e.g. T232) need denser points than the 1200-pt viewer package,
otherwise voxel marching-cubes shatters into floating fragments.
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
import trimesh
from scipy import ndimage
from skimage import measure

ROOT = Path(r"D:\CFD_Shadow")
CROWNS_META = ROOT / "data" / "trees" / "crowns.meta.json"
CROWNS_BIN = ROOT / "data" / "trees" / "crowns.bin"
INVENTORY = Path(r"D:\PolyU_Dashboard\PolyU_Trees_FINAL_421.csv.csv")
LAZ_DIR = Path(r"Z:\Carbon Neutrality\Segmented Individual Trees")
OUT_GLB = ROOT / "data" / "trees" / "trees_solid.glb"
OUT_META = ROOT / "data" / "trees" / "trees_solid.meta.json"
PUBLIC = ROOT / "dashboard" / "public" / "trees"


def load_dbh_map() -> dict[int, float]:
    out: dict[int, float] = {}
    if not INVENTORY.exists():
        return out
    with INVENTORY.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            tid_raw = row.get("Tree ID") or row.get("\ufeffTree ID") or ""
            m = re.search(r"(\d+)", tid_raw)
            if not m:
                continue
            tid = int(m.group(1))
            try:
                if row.get("DBH_cm"):
                    radius_m = (float(row["DBH_cm"]) / 100.0) * 0.5
                else:
                    radius_m = (float(row.get("DBH (mm)") or 0) / 1000.0) * 0.5
            except (TypeError, ValueError):
                continue
            out[tid] = max(0.05, min(0.9, radius_m))
    return out


def voxel_downsample(xyz: np.ndarray, voxel_m: float, max_points: int, rng: np.random.Generator) -> np.ndarray:
    if xyz.shape[0] == 0:
        return xyz
    mins = xyz.min(axis=0)
    keys = np.floor((xyz - mins) / voxel_m).astype(np.int64)
    span = keys.max(axis=0) - keys.min(axis=0) + 1
    packed = keys[:, 0] + keys[:, 1] * (span[0] + 1) + keys[:, 2] * (span[0] + 1) * (span[1] + 1)
    _, idx = np.unique(packed, return_index=True)
    out = xyz[idx]
    if out.shape[0] > max_points:
        out = out[rng.choice(out.shape[0], size=max_points, replace=False)]
    return out


def load_dense_local(
    tid: int,
    file_name: str | None,
    origin: np.ndarray,
    rng: np.random.Generator,
    *,
    sample_voxel: float,
    max_points: int,
) -> np.ndarray | None:
    """Reload original LAZ/LAS in local ENU for high-quality meshing."""
    candidates = []
    if file_name:
        candidates.append(LAZ_DIR / file_name)
    candidates.extend(
        [
            LAZ_DIR / f"RTK_T{tid}.laz",
            LAZ_DIR / f"RTK_T{tid}.las",
        ]
    )
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        return None
    las = laspy.read(str(path))
    xyz = np.column_stack((np.asarray(las.x), np.asarray(las.y), np.asarray(las.z))).astype(np.float64)
    xyz = xyz[np.isfinite(xyz).all(axis=1)]
    if xyz.shape[0] < 30:
        return None
    local = (xyz - origin).astype(np.float64)
    return voxel_downsample(local, sample_voxel, max_points, rng)


def keep_largest_component(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    try:
        parts = mesh.split(only_watertight=False)
    except Exception:
        return mesh
    if not parts:
        return mesh
    parts = sorted(parts, key=lambda m: len(m.faces), reverse=True)
    # Keep largest; if second is almost as big and nearby, merge top 2
    keep = [parts[0]]
    if len(parts) > 1 and len(parts[1].faces) > 0.35 * len(parts[0].faces):
        c0 = parts[0].centroid
        c1 = parts[1].centroid
        if float(np.linalg.norm(c0 - c1)) < 8.0:
            keep.append(parts[1])
    if len(keep) == 1:
        return keep[0]
    return trimesh.util.concatenate(keep)


def mesh_quality_ok(mesh: trimesh.Trimesh, pts: np.ndarray) -> bool:
    """Reject shattered crowns (too many tiny pieces / too little volume)."""
    if mesh is None or len(mesh.faces) < 8:
        return False
    try:
        parts = mesh.split(only_watertight=False)
        n_parts = len(parts)
        largest = max((len(p.faces) for p in parts), default=0)
    except Exception:
        n_parts, largest = 1, len(mesh.faces)
    if n_parts >= 6 and largest < 0.55 * len(mesh.faces):
        return False
    # Volume vs bbox for a filled canopy should not be tiny
    try:
        vol = float(abs(mesh.volume)) if mesh.is_watertight else float(mesh.convex_hull.volume)
        bbox = pts.max(axis=0) - pts.min(axis=0)
        bbox_vol = float(np.prod(np.maximum(bbox, 0.2)))
        if bbox_vol > 1 and vol < 0.02 * bbox_vol:
            return False
    except Exception:
        pass
    return True


def voxel_crown_mesh(xyz: np.ndarray, voxel: float, max_faces: int) -> trimesh.Trimesh | None:
    if xyz.shape[0] < 12:
        return None
    extent = xyz.max(axis=0) - xyz.min(axis=0)
    # Adaptive voxel: keep ~25–40 cells across the longest side
    long = float(np.max(extent))
    voxel = float(np.clip(long / 32.0, 0.18, max(voxel, 0.25)))

    mins = xyz.min(axis=0) - 1.5 * voxel
    maxs = xyz.max(axis=0) + 1.5 * voxel
    dims = np.ceil((maxs - mins) / voxel).astype(int) + 1
    if int(np.prod(dims)) > 3_000_000:
        voxel = float(np.max(maxs - mins) / 45.0)
        dims = np.ceil((maxs - mins) / voxel).astype(int) + 1

    grid = np.zeros(dims, dtype=bool)
    idx = np.floor((xyz - mins) / voxel).astype(int)
    idx = np.clip(idx, 0, dims - 1)
    grid[idx[:, 0], idx[:, 1], idx[:, 2]] = True

    # Stronger close for large / sparse crowns
    iters = 2 if long > 12 else 1
    grid = ndimage.binary_dilation(grid, iterations=iters)
    grid = ndimage.binary_closing(grid, iterations=iters + 1)
    # Fill small holes inside crown
    grid = ndimage.binary_fill_holes(grid)

    if int(grid.sum()) < 8:
        return None
    try:
        verts, faces, _n, _v = measure.marching_cubes(
            grid.astype(np.float32), level=0.5, spacing=(voxel, voxel, voxel)
        )
    except Exception:
        return None
    verts = verts + mins
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
    mesh = keep_largest_component(mesh)
    mesh.fix_normals()
    if len(mesh.faces) > max_faces:
        try:
            mesh = mesh.simplify_quadric_decimation(face_count=max_faces)
        except Exception:
            pass
    if len(mesh.faces) < 4:
        return None
    return mesh


def convex_fallback(xyz: np.ndarray) -> trimesh.Trimesh | None:
    if xyz.shape[0] < 4:
        return None
    try:
        # Mild outlier trim so hull follows canopy, not flyers
        med = np.median(xyz, axis=0)
        d = np.linalg.norm(xyz - med, axis=1)
        keep = xyz[d <= np.percentile(d, 97)]
        if keep.shape[0] < 4:
            keep = xyz
        hull = trimesh.Trimesh(vertices=keep, process=True).convex_hull
        if len(hull.faces) < 4:
            return None
        return hull
    except Exception:
        return None


def make_trunk(xyz: np.ndarray, radius_m: float, z0: float, z1: float) -> trimesh.Trimesh | None:
    if z1 <= z0 + 0.3:
        return None
    cx = float(np.median(xyz[:, 0]))
    cy = float(np.median(xyz[:, 1]))
    z_span = float(xyz[:, 2].max() - xyz[:, 2].min())
    low = xyz[xyz[:, 2] <= xyz[:, 2].min() + 0.35 * max(z_span, 1.0)]
    if low.shape[0] >= 8:
        d = np.hypot(low[:, 0] - cx, low[:, 1] - cy)
        r_est = float(np.percentile(d, 60))
        radius_m = float(np.clip(0.55 * radius_m + 0.45 * max(r_est, 0.05), 0.08, 1.1))
    height = float(z1 - z0)
    trunk = trimesh.creation.cylinder(radius=radius_m, height=height, sections=12)
    verts = trunk.vertices.copy()
    z_lo, z_hi = verts[:, 2].min(), verts[:, 2].max()
    t = (verts[:, 2] - z_lo) / max(z_hi - z_lo, 1e-6)
    scale = 1.0 - 0.28 * t
    verts[:, 0] *= scale
    verts[:, 1] *= scale
    trunk.vertices = verts
    trunk.apply_translation([cx, cy, z0 + 0.5 * height])
    return trunk


def to_three(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    v = mesh.vertices.copy()
    out = np.empty_like(v)
    out[:, 0] = v[:, 0]
    out[:, 1] = v[:, 2]
    out[:, 2] = -v[:, 1]
    mesh = mesh.copy()
    mesh.vertices = out
    return mesh


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voxel", type=float, default=0.35)
    ap.add_argument("--max-faces", type=int, default=500)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    meta = json.loads(CROWNS_META.read_text(encoding="utf-8"))
    xyz_all = np.fromfile(CROWNS_BIN, dtype=np.float32).reshape(-1, 3)
    origin = np.asarray(meta.get("origin_hk80") or [836318.0, 818150.0, 2.0], dtype=np.float64)
    trees = meta["trees"]
    if args.limit > 0:
        trees = trees[: args.limit]

    dbh = load_dbh_map()
    rng = np.random.default_rng(7)
    scene = trimesh.Scene()
    records = []
    failed = []
    crown_meshes: list[trimesh.Trimesh] = []
    trunk_meshes: list[trimesh.Trimesh] = []
    dense_used = 0

    print(f"Meshing {len(trees)} trees voxel~{args.voxel} max_faces={args.max_faces}")
    for i, t in enumerate(trees, 1):
        tid = int(t["tree_id"])
        off = int(t["offset"])
        n = int(t["count"])
        pts = xyz_all[off : off + n].astype(np.float64)
        if pts.shape[0] < 12:
            failed.append(f"T{tid}: too few points")
            continue

        extent = pts.max(axis=0) - pts.min(axis=0)
        long = float(np.max(extent))
        raw_n = int(t.get("raw_points") or 0)
        # Big / dense LAZ trees: remesh from original file with more points
        needs_dense = long >= 10.0 or raw_n >= 150_000 or (t.get("crown_spread_m") or 0) >= 10
        method = "package"
        if needs_dense:
            sample_voxel = 0.18 if long >= 15 else 0.22
            max_pts = 14000 if long >= 15 else 8000
            dense = load_dense_local(
                tid,
                t.get("file"),
                origin,
                rng,
                sample_voxel=sample_voxel,
                max_points=max_pts,
            )
            if dense is not None and dense.shape[0] >= pts.shape[0]:
                pts = dense
                dense_used += 1
                method = "dense_laz"

        zmin = float(pts[:, 2].min())
        zmax = float(pts[:, 2].max())
        zspan = max(zmax - zmin, 0.5)
        trunk_top = zmin + min(0.32 * zspan, 4.5)
        crown_pts = pts[pts[:, 2] >= zmin + 0.12 * zspan]
        if crown_pts.shape[0] < 20:
            crown_pts = pts

        face_budget = args.max_faces
        if long >= 15:
            face_budget = max(args.max_faces, 900)
        elif long >= 10:
            face_budget = max(args.max_faces, 650)

        # Large broad canopies (e.g. T232 Khaya): voxel isosurfaces look shattered.
        # Use a solid convex envelope of the measured crown points instead.
        prefer_hull = long >= 12.0 or (t.get("crown_spread_m") or 0) >= 10
        crown = None
        if prefer_hull:
            crown = convex_fallback(crown_pts)
            if crown is not None:
                method = method + "+hull"
        if crown is None:
            crown = voxel_crown_mesh(crown_pts, args.voxel, face_budget)
            if crown is None or not mesh_quality_ok(crown, crown_pts):
                crown = convex_fallback(crown_pts)
                if crown is not None:
                    method = method + "+hull"
        if crown is None:
            failed.append(f"T{tid}: crown mesh failed")
            continue

        radius = dbh.get(tid, 0.18)
        trunk = make_trunk(pts, radius_m=radius, z0=max(0.0, zmin - 0.05), z1=trunk_top)
        crown = to_three(crown)
        zc = crown.vertices[:, 1]
        zc_t = (zc - zc.min()) / max(float(zc.max() - zc.min()), 1e-6)
        cols = np.zeros((len(crown.vertices), 4), dtype=np.uint8)
        cols[:, 0] = (28 + 50 * zc_t).astype(np.uint8)
        cols[:, 1] = (110 + 90 * zc_t).astype(np.uint8)
        cols[:, 2] = (40 + 20 * (1 - zc_t)).astype(np.uint8)
        cols[:, 3] = 255
        crown.visual.vertex_colors = cols
        crown_meshes.append(crown)

        if trunk is not None:
            trunk = to_three(trunk)
            trunk.visual.vertex_colors = np.tile(
                np.array([92, 58, 30, 255], dtype=np.uint8), (len(trunk.vertices), 1)
            )
            trunk_meshes.append(trunk)

        records.append(
            {
                "tree_id": tid,
                "crown_faces": int(len(crown.faces)),
                "crown_verts": int(len(crown.vertices)),
                "has_trunk": trunk is not None,
                "trunk_radius_m": round(radius, 3),
                "z_min": round(zmin, 3),
                "z_max": round(zmax, 3),
                "method": method,
                "n_points_used": int(pts.shape[0]),
            }
        )
        if i % 25 == 0 or i == len(trees):
            print(f"  [{i}/{len(trees)}] ok={len(records)} dense={dense_used} failed={len(failed)}")

    if not records:
        print("No meshes created", file=sys.stderr)
        return 1

    crowns_batch = trimesh.util.concatenate(crown_meshes)
    scene.add_geometry(crowns_batch, node_name="crowns", geom_name="crowns")
    if trunk_meshes:
        trunks_batch = trimesh.util.concatenate(trunk_meshes)
        scene.add_geometry(trunks_batch, node_name="trunks", geom_name="trunks")

    OUT_GLB.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    OUT_GLB.write_bytes(scene.export(file_type="glb"))
    meta_out = {
        "version": 2,
        "n_trees": len(records),
        "n_failed": len(failed),
        "n_dense_laz": dense_used,
        "failed_sample": failed[:30],
        "voxel_m": args.voxel,
        "max_faces": args.max_faces,
        "glb": str(OUT_GLB),
        "bytes": OUT_GLB.stat().st_size,
        "note": "Solid crowns; large trees remeshed from dense LAZ to avoid shattered canopies.",
        "trees": records,
    }
    OUT_META.write_text(json.dumps(meta_out), encoding="utf-8")
    shutil.copy2(OUT_GLB, PUBLIC / "trees_solid.glb")
    shutil.copy2(OUT_META, PUBLIC / "trees_solid.meta.json")
    print(
        f"Wrote {len(records)} solid trees -> {OUT_GLB} "
        f"({OUT_GLB.stat().st_size / 1e6:.1f} MB) dense_laz={dense_used} failed={len(failed)}"
    )
    # Sanity on T232 if present
    for tid in (232, 234):
        row = next((r for r in records if r["tree_id"] == tid), None)
        if row:
            print(f"  T{tid}: {row}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
