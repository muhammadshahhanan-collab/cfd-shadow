# Context buildings/roads + real crowns — options (2026-10-28)

Goal: wider campus look (≈1–2 km) with real building/road shapes; PolyU trees as measured crowns for shadow work (not cartoon icons).

## What 3d.map.gov.hk actually is

Open3Dhk is a **viewer**. Usable data is the LandsD / CSDI products behind it — do **not** scrape the website.

| Product | What you get | Fit for us |
|--------|----------------|------------|
| **Building footprints** (CSDI ArcGIS; script already in `scripts/export_landsd_buildings.py`) | Official plan + Top/Base height, Tower/Podium types | **Best practical LOD1** for 1–2 km extrusions. Probe: **~5.3k** @ 1.5 km, **~8.8k** @ 2 km around PolyU |
| **3D Spatial Data API** (Cesium 3D Tiles: `building`, `infrastructure`) | Streaming LOD models like the portal | Best “looks like 3d.map.gov.hk” for buildings/infra; needs Cesium or 3D Tiles loader + API key / ToS |
| **3D Visualisation Map — Individualised** (glTF/FBX/MAX per iB1000 sheet) | Textured building + road + **vegetation** + terrain objects | Strong visual context; vegetation is **generic styled**, not our RTK crowns |
| **3D Visualisation Map — Tile-based** (oblique mesh / 3D Tiles) | Photoreal continuous mesh | Pretty backdrop; hard to separate buildings vs trees for CFD/shadow |
| **3D Pedestrian Network** | Official 3D walkway/path lines (GeoJSON/GML/FGDB) | **Best campus tracks/paths** vs sparse OSM footways |
| **OSM** (script: `export_context_buildings.py`) | Free buildings + highways | Already used in wind package; footprints/heights weaker than LandsD |

Current dashboard wind package: **115** extruded OSM buildings, **399** road segs (many footways), extent ~432×576 m — that is why it looks clipped and “not original shapes.”

## Recommended stack (buildings / roads / paths)

1. **Buildings (1.5–2 km):** LandsD footprints → extrude by Top−Base (keep Tower+Podium). Optional upgrade later: stream 3D Tiles or load sheet glTF for richer façades.
2. **Roads + campus paths:** LandsD / OSM highways for carriageways + **3D Pedestrian Network** for walkways/tracks inside and around campus.
3. **Radius:** start **1.5 km** (scripts already target this); go **2 km** if framing needs more city context. CFD wind field can stay on the smaller domain; only the **visual context** expands.

Do **not** use 3D Map HK vegetation for PolyU shadow science.

## Trees — what we can get that is “real”

| Source | Coverage | Shape fidelity | Shadow usefulness |
|--------|----------|----------------|-------------------|
| **Segmented LAZ** (`Z:\…\RTK_T*.laz`) | ~756 files; catalog `has_segmented_laz` ≈744 | **Measured** asymmetric crown XYZ (e.g. T1 ≈174k pts, XY extent ~5×4 m, Z ~6 m) | **Primary** — occupancy / alpha-shape / voxel mesh = true shadow outline |
| **Campus catalog** `trees_campus_all.csv` | 784 rows; height + crown_spread ≈751 | Ellipsoid / disk only | Good QC + fallback if LAZ missing; alone = still “blob” |
| **Inventory DBH** `PolyU_Trees_FINAL_421.csv` | 421 trees; DBH_cm / Height / Crown Spread | Trunk radius only | Trunk thickness + validation; **does not** define crown silhouette |
| **3D Map HK vegetation models** | Territory-wide styled assets | Look nice, not our trees | Context only; **wrong** for measured PolyU shadows |

Fidelity ladder (PolyU only):

1. **Best (measurement):** LAZ → dense points or voxel / alpha-shape hull (asymmetric).
2. **Good (viz + cast):** LAZ → solid mesh (`export_solid_trees.py` already exists; denser voxels for large trees like T232).
3. **Fallback:** inventory ellipsoid (H × crown_spread) + DBH trunk — better than cones, still not “original crown.”

Scripts already drafted (not fully wired into the new dashboard yet):

- `scripts/export_laz_crowns.py` → browser point package  
- `scripts/export_solid_trees.py` → solid GLB from LAZ (+ DBH trunks)  
- `scripts/export_landsd_buildings.py` / `export_context_buildings.py` → 1.5 km context  

Dashboard still renders **cartoon** crowns from `public/wind/trees.json` inside `WindFlowViewer`.

## Verdict

| Need | Best option |
|------|-------------|
| Real building footprints & heights out to 1–2 km | **LandsD CSDI buildings** (then optional 3D Tiles/glTF) |
| Real campus tracks/paths | **3D Pedestrian Network** + road lines |
| Real PolyU crown shapes for shadows | **Our LAZ**, constrained by inventory H / crown / DBH |
| Pretty backdrop like Open3Dhk | Sheet **glTF** or tile-based mesh (secondary) |

## Suggested build order

1. Run LandsD 1.5 km buildings + pedestrian network into `dashboard/public/` and show them in the viewer.  
2. Export LAZ crowns (points + solid meshes) for PolyU only; replace cartoon trees.  
3. Add simple sun/shadow pass on LAZ meshes (not on inventory spheres).  
4. Optional: Cesium/Three 3D Tiles or sheet glTF for richer building look.

## Status (2026-10-28 evening)

Done and live on `http://localhost:5174/`:

| Asset | Result |
|-------|--------|
| LandsD buildings | **4241** raw → **~2966** viewer-filtered (~1.5 km) in `dashboard/public/buildings/context_1p5km.json` |
| Pedestrian network | **~22k** raw → **~5.5k** campus-focused in `roads_1p5km.json` |
| OSM vehicle roads | Overpass timed out; interim **wind-package** vehicle roads (~164) |
| LAZ points | **684** crowns / 678k pts → `public/trees/crowns.bin` |
| LAZ solids | **684** meshes → `public/trees/trees_solid.glb` (~6.9 MB); dashboard prefers GLB |

Rebuild helpers: `scripts/build_dashboard_layers.py`, `export_pedestrian_network.py`, `export_laz_crowns.py`, `export_solid_trees.py`.
