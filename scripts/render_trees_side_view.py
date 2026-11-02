"""Render a presentable side-elevation of measured LAZ solid crowns for ITF slides."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyvista as pv
import trimesh

ROOT = Path(r"D:\CFD_Shadow")
GLB = ROOT / "data" / "trees" / "trees_solid.glb"
OUT = ROOT / "outputs" / "ppt_media" / "trees_side_elevation.png"

FOCUS_E, FOCUS_N = 230.0, 150.0
RADIUS = 100.0


def clip_horizontal(mesh: trimesh.Trimesh, focus_e: float, focus_n: float, radius: float) -> trimesh.Trimesh:
    """Keep faces whose centroids lie inside a horizontal disc (display coords)."""
    v = np.asarray(mesh.vertices)
    f = np.asarray(mesh.faces)
    cents = v[f].mean(axis=1)
    # display: x=east, y=up, z=-north
    de = cents[:, 0] - focus_e
    dn = (-cents[:, 2]) - focus_n
    keep = de * de + dn * dn <= radius * radius
    if not np.any(keep):
        return mesh
    return mesh.submesh([np.where(keep)[0]], append=True)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    scene = trimesh.load(GLB, force="scene")

    plotter = pv.Plotter(off_screen=True, window_size=(1600, 1000))
    plotter.set_background("#F4F7FA")

    ground = pv.Plane(
        center=(FOCUS_E, 0.05, -FOCUS_N),
        direction=(0, 1, 0),
        i_size=RADIUS * 2.2,
        j_size=RADIUS * 2.2,
    )
    plotter.add_mesh(ground, color="#D8CEBB", opacity=0.9)

    n_faces = 0
    for name, geom in scene.geometry.items():
        if not isinstance(geom, trimesh.Trimesh) or len(geom.faces) == 0:
            continue
        clipped = clip_horizontal(geom, FOCUS_E, FOCUS_N, RADIUS)
        if clipped is None or len(clipped.faces) == 0:
            continue
        mesh = pv.wrap(clipped)
        # Heuristic: trunks = smaller vertical cylinders; crowns = bulk foliage
        lname = str(name).lower()
        if "trunk" in lname:
            color = "#6B4F2A"
        else:
            # also detect by aspect: low height span relative to area → crown
            height = float(np.ptp(np.asarray(clipped.vertices)[:, 1]))
            color = "#6B4F2A" if height < 8.0 and clipped.area < 800 else "#2F9E44"
        plotter.add_mesh(mesh, color=color, smooth_shading=False, show_edges=False)
        n_faces += len(clipped.faces)

    # Side elevation from the south, slight azimuth for depth
    cam = (FOCUS_E + 35.0, 22.0, -FOCUS_N + 145.0)
    focal = (FOCUS_E, 10.0, -FOCUS_N)
    plotter.camera_position = [cam, focal, (0, 1, 0)]
    plotter.camera.zoom(1.35)
    plotter.add_text(
        "Measured LAZ crown geometry — side elevation",
        font_size=12,
        color="#222222",
        position="upper_left",
    )
    plotter.show(screenshot=str(OUT))
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes, faces={n_faces})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
