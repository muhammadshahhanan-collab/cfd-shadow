"""Make two orbiting 3D GIFs: LAZ point crowns vs solid meshed trees.

Outputs:
  D:\\CFD_Shadow\\outputs\\gifs\\trees_pointcloud_orbit.gif
  D:\\CFD_Shadow\\outputs\\gifs\\trees_solid_orbit.gif
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyvista as pv
import trimesh

ROOT = Path(r"D:\CFD_Shadow")
META = ROOT / "data" / "trees" / "crowns.meta.json"
BIN = ROOT / "data" / "trees" / "crowns.bin"
GLB = ROOT / "data" / "trees" / "trees_solid.glb"
OUT = ROOT / "outputs" / "gifs"

# Focus on the library / giant-tree courtyard (local ENU metres)
FOCUS = np.array([230.0, 150.0, 10.0])  # near T232/T234 + library
RADIUS = 110.0
N_FRAMES = 48
WINDOW = (1280, 800)


def enu_to_display(xyz: np.ndarray) -> np.ndarray:
    """Match dashboard: x east, y up, z = -north."""
    out = np.empty_like(xyz)
    out[:, 0] = xyz[:, 0]
    out[:, 1] = xyz[:, 2]
    out[:, 2] = -xyz[:, 1]
    return out


def focus_mask_enu(xyz: np.ndarray) -> np.ndarray:
    d = np.hypot(xyz[:, 0] - FOCUS[0], xyz[:, 1] - FOCUS[1])
    return d <= RADIUS


def load_points() -> tuple[np.ndarray, np.ndarray]:
    meta = json.loads(META.read_text(encoding="utf-8"))
    xyz = np.fromfile(BIN, dtype=np.float32).reshape(-1, 3)
    # Keep trees whose centroids are in the focus disc
    keep_idx = []
    for t in meta["trees"]:
        off, n = int(t["offset"]), int(t["count"])
        if np.hypot(t["cx"] - FOCUS[0], t["cy"] - FOCUS[1]) <= RADIUS:
            keep_idx.append(np.arange(off, off + n))
    if not keep_idx:
        # fallback: spatial filter all points
        m = focus_mask_enu(xyz)
        pts = xyz[m]
    else:
        pts = xyz[np.concatenate(keep_idx)]
    disp = enu_to_display(pts)
    # colour by height
    z = disp[:, 1]
    t = (z - z.min()) / max(float(z.max() - z.min()), 1e-6)
    colors = np.column_stack(
        [
            0.10 + 0.35 * t,
            0.40 + 0.50 * t,
            0.12 + 0.10 * (1 - t),
        ]
    )
    return disp, colors


def load_solids() -> pv.PolyData:
    scene = trimesh.load(GLB, force="scene")
    geoms = []
    for name, geom in scene.geometry.items():
        if not isinstance(geom, trimesh.Trimesh):
            continue
        # GLB already in Three/display coords
        v = np.asarray(geom.vertices)
        # Keep faces near focus (focus in ENU → display)
        focus_d = np.array([FOCUS[0], FOCUS[2], -FOCUS[1]])
        c = v.mean(axis=0)
        # rough distance in XZ (horizontal in display)
        if np.hypot(c[0] - focus_d[0], c[2] - focus_d[2]) > RADIUS + 30:
            continue
        geoms.append(geom)
    if not geoms:
        # take all if filter too strict
        geoms = [g for g in scene.geometry.values() if isinstance(g, trimesh.Trimesh)]
    mesh = trimesh.util.concatenate(geoms)
    faces = np.hstack([np.full((len(mesh.faces), 1), 3), mesh.faces]).astype(np.int64)
    poly = pv.PolyData(np.asarray(mesh.vertices), faces)
    # Prefer crown-ish greens; trunks are brownish in separate geom names
    return poly


def style_plotter(plotter: pv.Plotter, title: str) -> None:
    plotter.set_background("#07111c")
    plotter.add_text(
        title,
        font_size=12,
        color="white",
        position="upper_left",
        shadow=True,
    )
    # Ground disc hint
    ground = pv.Disc(
        center=(FOCUS[0], 0.0, -FOCUS[1]),
        inner=0,
        outer=RADIUS + 20,
        normal=(0, 1, 0),
        r_res=1,
        c_res=48,
    )
    plotter.add_mesh(ground, color="#0c1828", opacity=0.95)


def orbit_gif(
    add_actors,
    out_path: Path,
    title: str,
) -> None:
    pv.OFF_SCREEN = True
    plotter = pv.Plotter(off_screen=True, window_size=WINDOW)
    style_plotter(plotter, title)
    add_actors(plotter)

    focus_d = np.array([FOCUS[0], 7.0, -FOCUS[1]])
    plotter.camera.focal_point = focus_d
    # Oblique orbit — reads as 3D (not top-down)
    dist = 125.0
    elev = 32.0
    frames = []
    for i in range(N_FRAMES):
        az = 360.0 * i / N_FRAMES
        rad = np.deg2rad(az)
        elev_rad = np.deg2rad(elev)
        eye = focus_d + np.array(
            [
                dist * np.cos(elev_rad) * np.cos(rad),
                dist * np.sin(elev_rad) + 8.0,
                dist * np.cos(elev_rad) * np.sin(rad),
            ]
        )
        plotter.camera.position = eye
        plotter.camera.focal_point = focus_d
        plotter.camera.up = (0, 1, 0)
        plotter.render()
        img = plotter.screenshot(return_img=True)
        frames.append(img)
    plotter.close()

    import imageio.v2 as imageio

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Keep GIFs under email-friendly size while staying smooth
    imageio.mimsave(out_path, frames, duration=0.07, loop=0)
    print(f"Wrote {out_path} ({out_path.stat().st_size / 1e6:.2f} MB, {len(frames)} frames)")


def main() -> int:
    pts, cols = load_points()
    print(f"Point focus cloud: {len(pts)} points")

    def add_points(plotter: pv.Plotter) -> None:
        cloud = pv.PolyData(pts)
        cloud["rgb"] = cols
        plotter.add_points(
            cloud,
            scalars="rgb",
            rgb=True,
            point_size=4.5,
            render_points_as_spheres=True,
        )

    orbit_gif(
        add_points,
        OUT / "trees_pointcloud_orbit.gif",
        "PolyU trees · LAZ point crowns (measured)",
    )

    solids = load_solids()
    print(f"Solid mesh: {solids.n_points} verts / {solids.n_cells} cells")

    def add_solids(plotter: pv.Plotter) -> None:
        # Split roughly by colour heuristics is hard after concat; render as foliage green
        # and overlay thinner brown trunks if separate geoms exist in GLB
        scene = trimesh.load(GLB, force="scene")
        focus_d = np.array([FOCUS[0], FOCUS[2], -FOCUS[1]])
        for name, geom in scene.geometry.items():
            if not isinstance(geom, trimesh.Trimesh):
                continue
            v = np.asarray(geom.vertices)
            c = v.mean(axis=0)
            if np.hypot(c[0] - focus_d[0], c[2] - focus_d[2]) > RADIUS + 35:
                continue
            faces = np.hstack([np.full((len(geom.faces), 1), 3), geom.faces]).astype(np.int64)
            poly = pv.PolyData(v, faces)
            is_trunk = "trunk" in str(name).lower()
            plotter.add_mesh(
                poly,
                color="#6b4423" if is_trunk else "#2f9a48",
                smooth_shading=not is_trunk,
                show_edges=False,
                opacity=1.0,
            )

    orbit_gif(
        add_solids,
        OUT / "trees_solid_orbit.gif",
        "PolyU trees · solid LAZ crowns + trunks",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
