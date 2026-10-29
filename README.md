# CFD_Shadow

New CFD / trees / wind base (separate from PolyU ET product).

**Start here:** [AGENT_HANDOFF.md](AGENT_HANDOFF.md)

## Wind dashboard

Standalone viewer for the existing tree-based CFD package:

```bash
cd dashboard
npm install
npm run dev
```

Open http://127.0.0.1:5175/ (PolyU dashboard stays on 5174)

Static layers:

- `dashboard/public/wind/` — CFD wind package
- `dashboard/public/buildings/` — LandsD ~1.5 km footprints + ped paths
- `dashboard/public/trees/` — measured LAZ crowns (`crowns.bin` / `trees_solid.glb`)

Rebuild context / crowns:

```bash
python scripts/build_dashboard_layers.py
D:\CFD\.venv\Scripts\python.exe scripts/export_laz_crowns.py
D:\CFD\.venv\Scripts\python.exe scripts/export_solid_trees.py
```

