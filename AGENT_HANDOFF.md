# Agent handoff — CFD_Shadow (new project base)

**Give this file to the new agent.**  
User: Muhammad · PolyU-related CFD / trees / wind work · prefers direct code iteration.

---

## 1. Two folders (do not mix)

| Folder | Role |
|--------|------|
| `D:\CFD` | **Original** PolyU campus twin: wind CFD, LandsD buildings, ET cooling pilot, DART discussion |
| `D:\CFD_Shadow` | **New project base** — clone/enhance separately; will become its own dashboard (not PolyU-branded product). Focus: CFD + real LiDAR trees + wind + later **shadow from true crowns** |

Work for the new project happens in **`D:\CFD_Shadow`**. Only **read** `D:\CFD` / `Z:\` as sources unless the user says to change the original.

---

## 2. What the original project (`D:\CFD`) already has

### Wind / CFD
- Python package: `D:\CFD\canopy_cfd\` (LAD voxels, OpenFOAM case helpers, HKO wind, buildings, DSM, export).
- Domains: `D:\CFD\outputs\domains\` e.g. `seed135_r500` (main), `domain_lad.npz` with `lad_m2_m3`.
- Dashboard / viewer pieces live under the original repo (e.g. WindFlowViewer + LandsD GLB buildings) — locate under `D:\CFD` when cloning UI.
- Pedestrian wind validation vs Airflow Analyst was done earlier in that project.

### Trees (server)
- Segmented crowns: `Z:\Carbon Neutrality\Segmented Individual Trees\` → `RTK_T*.laz` / `.las` (**~744–752** files; **re-count on start** — server may have updated).
- Master inventory: `Z:\Carbon Neutrality\master_polyu_carbon_neutrality_tree1.xlsx` (~751 rows, Easting/Northing, height, crown spread).
- RTK coords: `Z:\Carbon Neutrality\Individual Tree Coordinates_RTK_points.csv`.
- Campus catalog already built: `D:\CFD\ET\data\trees_campus_all.csv` (**copied** → `D:\CFD_Shadow\data\trees\`).

### ET / cooling pilot (context only — not the new product goal)
- Folder: `D:\CFD\ET\`
- Method: **FAO-56 Penman–Monteith + LAI** → cooling **ΔT estimate** (not DART).
- Z-block was missing (domain clipped at N≈818600); fixed via campus LAI.
- Map: `D:\CFD\ET\outputs\cooling_map_panel.png`
- Assumptions: well-watered soil, clear-sky / HKO solar gaps — see `D:\CFD\ET\docs\missing_data_assumptions.md`
- Honest line for prof: *PM+LAI = estimated canopy cooling ΔT; DART = 3D radiative/thermal simulation.*

### DART (upgrade path discussed; not installed here)
- Download needs **ORCID / AERIS login** + access approval: https://dart.omp.eu/ / https://www.cesbio.cnrs.fr/dart/en/request-access/
- Grey DOWNLOAD + “Sign-in required” = not authorized yet.
- Scene pack example: `D:\CFD\ET\docs\dart_scene_20260930_1200\` (HKO KP GSR etc.)
- Workflow notes: `D:\CFD\ET\docs\DART_download_and_LAZ_workflow.md`

---

## 3. New project intent (`D:\CFD_Shadow`)

**Base:** clone CFD + trees + wind datasets into this folder so it can grow into a **separate dashboard**.

**Near-term enhancement (user priority):**
- Trees must use **original LiDAR crown shape / height / extent** — **not** cartoon spheres/cones.
- Reason: **measure shadows** from real crowns → need true geometry from LAZ.

**Modules to keep clear:**
1. **Trees** (LAZ → real crown mesh / voxels)  
2. **Wind** (CFD / fields)  
3. Later: shadow / sun geometry on those crowns  

ET/DART PolyU cooling can stay referenced but is **not** the first deliverable of this clone.

---

## 4. Already seeded in `D:\CFD_Shadow`

```
D:\CFD_Shadow\
  AGENT_HANDOFF.md          ← this file
  docs\                     ← put more notes here
  data\
    trees\                  ← catalogs copied from ET
      trees_campus_all.csv
      trees_campus_summary.json
      vegetation_summary.json
    hko\                    ← King's Park snapshot copied from ET
    wind\                   ← empty; copy wind packages next
```

**Not yet copied (do on “start clone”):** full `canopy_cfd` code, OpenFOAM/domain outputs, dashboard UI, **all LAZ files** (large — prefer junction/symlink to `Z:\` or selective copy).

---

## 5. Suggested first tasks for the new agent

When user says **start**:

1. **Re-scan** `Z:\Carbon Neutrality\Segmented Individual Trees` → count LAZ/LAS; refresh `data\trees\` catalog if IDs changed (~752 target).
2. **Clone base code** from `D:\CFD` into `D:\CFD_Shadow` (e.g. `canopy_cfd`, needed `scripts`, minimal dashboard/wind viewer assets) — keep packages importable.
3. **Copy or link datasets:**
   - LAD: `D:\CFD\outputs\domains\seed135_r500\domain_lad.npz` (+ `domain_meta.json` if present)
   - Wind export package used by the viewer (search under `D:\CFD\outputs` / dashboard folders)
   - DSM / LandsD building mesh if required for shadows + wind
4. **Do not** cartoon-render trees as the end state; plan LAZ → crown hull / alpha-shape / voxel mesh for shadow casting.
5. Keep **`D:\CFD` untouched** unless user asks for a fix there.

---

## 6. One-liner glossary

| Term | Meaning |
|------|---------|
| Cooling pilot | First PM+LAI ΔT test map; illustrative, not final thermal truth |
| DART | CESBIO 3D radiative transfer (thermal/RB); needs login + real scene inputs |
| CFD_Shadow | New separate CFD/trees/wind base for real crowns + shadows + new dashboard |

---

## 7. Paste this to the new agent (short)

```
Read D:\CFD_Shadow\AGENT_HANDOFF.md end-to-end.
Original project: D:\CFD. New work only in D:\CFD_Shadow.
Goal: separate CFD base with trees+wind; next enhance real LiDAR crown shapes for shadow measurement (~752 LAZ on Z:\Carbon Neutrality\Segmented Individual Trees).
Do not treat the ET PM cooling map as DART. Ask me before large LAZ copies.
```

---

*Last updated: 2026-10-28 · Handoff from PolyU CFD / ET / DART discussion into CFD_Shadow.*
