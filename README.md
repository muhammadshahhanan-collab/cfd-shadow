# CFD_Shadow

Standalone CFD / trees / wind dashboard (separate from the PolyU ET product).

## Live

https://muhammadshahhanan-collab.github.io/cfd-shadow/

## Repo

https://github.com/muhammadshahhanan-collab/cfd-shadow

## Local

```bash
cd dashboard
npm install
npm run dev
```

Open http://127.0.0.1:5175/

Static layers:

- `dashboard/public/wind/` — CFD wind package
- `dashboard/public/buildings/` — LandsD ~1.5 km footprints + ped paths
- `dashboard/public/trees/` — measured LAZ crowns (`crowns.bin` / `trees_solid.glb`)

## Redeploy

```bash
cd dashboard
npm run build
```

Then publish `dashboard/dist` to the `gh-pages` branch.
