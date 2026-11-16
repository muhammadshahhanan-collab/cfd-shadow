import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import * as SunCalc from "suncalc";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import {
  HKO_AIR_TEMP_HEIGHT_M,
  getHkoAirTemp,
  getLazCrownsBin,
  getLazCrownsMeta,
  getSolidTreesMeta,
  getWindBuildings,
  getWindCampusBoundary,
  getWindLatest,
  getWindRoads,
  getWindStatus,
  getWindTrees,
} from "../services/windApi";

/** Poll HKO air temperature this often (not every 1 min). */
const HKO_AIR_TEMP_POLL_MS = 30 * 60 * 1000;
/** Keep AWS within this distance of the wind-domain centre for the heatmap. */
const HKO_TEMP_STATION_RADIUS_M = 4500;
/**
 * Absolute colour scale for HK screen air temp (°C).
 * Fixed range so roads read warm/cool honestly (not stretched to local min–max).
 */
const AIR_TEMP_COLOR_MIN_C = 18;
const AIR_TEMP_COLOR_MAX_C = 30;

/** PolyU main campus (WGS84) — solar ephemeris. */
const POLYU_LAT = 22.3045;
const POLYU_LON = 114.1795;

/** Package defaults from wind_latest.json viz (n_particles_default / time_scale). */
const TIME_SCALE = 10;
/** Campus-era baseline; Hung Hom capped for interactive FPS (see particleCountForDomain). */
const N_PARTICLES_BASE = 2800;
const N_PARTICLES_MAX = 7000; // 16k + long trails was stalling the browser
const CAMPUS_AREA_REF_M2 = 432 * 572;
const TRAIL_BASE = 10;
const TRAIL_DISTRICT = 8; // fewer segments → much cheaper LineSegments updates

function particleCountForDomain(nx, ny, dx, vizCount, district) {
  if (Number.isFinite(vizCount) && vizCount > 0) {
    return Math.min(N_PARTICLES_MAX, Math.max(1200, Math.round(vizCount)));
  }
  const area = Math.max(1, nx * dx * ny * dx);
  // Mild scale-up for district without melting the GPU.
  const factor = district ? Math.pow(area / CAMPUS_AREA_REF_M2, 0.35) : Math.sqrt(area / CAMPUS_AREA_REF_M2);
  const scaled = Math.round(N_PARTICLES_BASE * factor);
  return Math.min(N_PARTICLES_MAX, Math.max(N_PARTICLES_BASE, scaled));
}
const POLL_MS = 60_000;
const HOUR_MS = 3_600_000;
/**
 * Soft domain edge (SimScale / urbanVIS style): never show the CFD cuboid cut.
 * Particles fade + respawn inside a margin so the campus reads as a place, not a box.
 */
const EDGE_MARGIN_M = 22;
/**
 * Wind viz: PolyU campus boundary + 0.5 km buffer.
 * seed135 CFD grid is ~432×452 m, so the buffer fills the full available UVW field.
 */
const WIND_FOCUS_PAD_M = 500;
/** Pedestrian / tree-canopy wind only — 1.5 m AGL (not building-height bands). */
const PED_Z_M = 1.5;

/** Matplotlib turbo control points (same family as the share GIF). */
const TURBO_STOPS = [
  [0.0, 0.18995, 0.07176, 0.23217],
  [0.1, 0.27461, 0.17559, 0.59858],
  [0.2, 0.19015, 0.4051, 0.9062],
  [0.3, 0.08342, 0.6429, 0.94007],
  [0.4, 0.11732, 0.81269, 0.71458],
  [0.5, 0.43098, 0.89478, 0.36889],
  [0.6, 0.76168, 0.86053, 0.18296],
  [0.7, 0.96019, 0.70177, 0.16835],
  [0.8, 0.98719, 0.4566, 0.1707],
  [0.9, 0.90418, 0.2225, 0.15857],
  [1.0, 0.70567, 0.01556, 0.10556],
];

function decodeF16LE(b64) {
  const bin = atob(b64);
  const buf = new ArrayBuffer(bin.length);
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  const u16 = new Uint16Array(buf);
  const out = new Float32Array(u16.length);
  for (let i = 0; i < u16.length; i += 1) {
    const h = u16[i];
    const s = (h & 0x8000) >> 15;
    const e = (h & 0x7c00) >> 10;
    const f = h & 0x03ff;
    if (e === 0) {
      out[i] = (s ? -1 : 1) * 2 ** -14 * (f / 1024);
    } else if (e === 0x1f) {
      out[i] = f ? NaN : (s ? -1 : 1) * Infinity;
    } else {
      out[i] = (s ? -1 : 1) * 2 ** (e - 15) * (1 + f / 1024);
    }
  }
  return out;
}

function decodeU8(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
  return out;
}

function idx3(i, j, k, ny, nz) {
  return (i * ny + j) * nz + k;
}

function sampleGrid(arr, nx, ny, nz, dx, dz, x, y, z) {
  const fi = Math.min(Math.max(x / dx - 0.5, 0), nx - 1.0001);
  const fj = Math.min(Math.max(y / dx - 0.5, 0), ny - 1.0001);
  const fk = Math.min(Math.max(z / dz - 0.5, 0), nz - 1.0001);
  const i0 = fi | 0;
  const j0 = fj | 0;
  const k0 = fk | 0;
  const i1 = Math.min(i0 + 1, nx - 1);
  const j1 = Math.min(j0 + 1, ny - 1);
  const k1 = Math.min(k0 + 1, nz - 1);
  const ti = fi - i0;
  const tj = fj - j0;
  const tk = fk - k0;
  const c000 = arr[idx3(i0, j0, k0, ny, nz)];
  const c100 = arr[idx3(i1, j0, k0, ny, nz)];
  const c010 = arr[idx3(i0, j1, k0, ny, nz)];
  const c110 = arr[idx3(i1, j1, k0, ny, nz)];
  const c001 = arr[idx3(i0, j0, k1, ny, nz)];
  const c101 = arr[idx3(i1, j0, k1, ny, nz)];
  const c011 = arr[idx3(i0, j1, k1, ny, nz)];
  const c111 = arr[idx3(i1, j1, k1, ny, nz)];
  const c00 = c000 * (1 - ti) + c100 * ti;
  const c01 = c001 * (1 - ti) + c101 * ti;
  const c10 = c010 * (1 - ti) + c110 * ti;
  const c11 = c011 * (1 - ti) + c111 * ti;
  return (c00 * (1 - tj) + c10 * tj) * (1 - tk) + (c01 * (1 - tj) + c11 * tj) * tk;
}

function turboColor(t, target) {
  const x = Math.min(1, Math.max(0, t));
  let i = 0;
  while (i < TURBO_STOPS.length - 2 && x > TURBO_STOPS[i + 1][0]) i += 1;
  const a = TURBO_STOPS[i];
  const b = TURBO_STOPS[i + 1];
  const u = (x - a[0]) / (b[0] - a[0] || 1);
  target.setRGB(
    a[1] + (b[1] - a[1]) * u,
    a[2] + (b[2] - a[2]) * u,
    a[3] + (b[3] - a[3]) * u
  );
}

/** 0 at domain walls → 1 in the interior (kills the square-box silhouette). */
function edgeFade(x, y, Lx, Ly, margin) {
  const m = margin ?? EDGE_MARGIN_M;
  const mx = Math.min(x, Lx - x) / m;
  const my = Math.min(y, Ly - y) / m;
  return Math.min(1, Math.max(0, Math.min(mx, my)));
}

/** Keep wind trails inside PolyU + Z focus (soft kill outside). */
function focusFade(x, y, focus, margin = EDGE_MARGIN_M) {
  if (!focus) return 1;
  const fx0 = focus.x0 ?? 0;
  const fy0 = focus.y0 ?? 0;
  const fx1 = focus.x1 ?? x;
  const fy1 = focus.y1 ?? y;
  const mx = Math.min(x - fx0, fx1 - x) / margin;
  const my = Math.min(y - fy0, fy1 - y) / margin;
  return Math.min(1, Math.max(0, Math.min(mx, my)));
}

/** Pedestrian-level speed plane — strong over PolyU core, faint outside. */
function buildPedestrianPlane(S) {
  const { u, v, w, solid, nx, ny, nz, dx, dz, vmax, focus } = S;
  const k = Math.min(nz - 1, Math.max(0, Math.round(1.5 / dz - 0.5)));
  const tw = Math.min(320, nx);
  const th = Math.min(320, ny);
  const Lx = nx * dx;
  const Ly = ny * dx;
  const fx0 = focus?.x0 ?? 0;
  const fy0 = focus?.y0 ?? 0;
  const fx1 = focus?.x1 ?? Lx;
  const fy1 = focus?.y1 ?? Ly;
  const fcx = 0.5 * (fx0 + fx1);
  const fcy = 0.5 * (fy0 + fy1);
  const frx = 0.55 * (fx1 - fx0);
  const fry = 0.55 * (fy1 - fy0);
  const data = new Uint8Array(tw * th * 4);
  const c = new THREE.Color();
  for (let jj = 0; jj < th; jj += 1) {
    for (let ii = 0; ii < tw; ii += 1) {
      const i = Math.min(nx - 1, ((ii + 0.5) * nx) / tw) | 0;
      const j = Math.min(ny - 1, ((jj + 0.5) * ny) / th) | 0;
      const o = (jj * tw + ii) * 4;
      const x = (i + 0.5) * dx;
      const y = (j + 0.5) * dx;
      const inCore = x >= fx0 && x <= fx1 && y >= fy0 && y <= fy1;
      const rn = ((x - fcx) / frx) ** 2 + ((y - fcy) / fry) ** 2;
      const coreFade = Math.min(1, Math.max(0, 1 - (rn - 0.85) / 0.35));
      const fade = inCore ? Math.max(0.35, coreFade) : coreFade * 0.15;
      if (solid[idx3(i, j, k, ny, nz)] || fade < 0.08) {
        data[o + 3] = 0;
        continue;
      }
      const sp = Math.hypot(
        u[idx3(i, j, k, ny, nz)],
        v[idx3(i, j, k, ny, nz)],
        w[idx3(i, j, k, ny, nz)]
      );
      turboColor(sp / Math.max(vmax, 1e-6), c);
      data[o] = (c.r * 255) | 0;
      data[o + 1] = (c.g * 255) | 0;
      data[o + 2] = (c.b * 255) | 0;
      data[o + 3] = (Math.min(255, 140 * fade)) | 0;
    }
  }
  const tex = new THREE.DataTexture(data, tw, th, THREE.RGBAFormat);
  tex.needsUpdate = true;
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.magFilter = THREE.LinearFilter;
  tex.minFilter = THREE.LinearFilter;
  const mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(Lx, Ly),
    new THREE.MeshBasicMaterial({
      map: tex,
      transparent: true,
      opacity: 1,
      depthWrite: false,
      side: THREE.DoubleSide,
    })
  );
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.set(Lx * 0.5, 0.35, -Ly * 0.5);
  mesh.renderOrder = 2;
  return mesh;
}

/**
 * Roads / LandsD ped paths as batched LineSegments (continuous look, few draw calls).
 */
function buildRoads(roadsPayload) {
  const group = new THREE.Group();
  group.renderOrder = 0;
  const segs = roadsPayload?.segments || [];

  const roadMat = new THREE.LineBasicMaterial({
    color: 0xf0f3f7,
    transparent: true,
    opacity: 0.96,
    depthWrite: false,
  });
  const pathMat = new THREE.LineBasicMaterial({
    color: 0xd5dde6,
    transparent: true,
    opacity: 0.9,
    depthWrite: false,
  });

  const roadPairs = [];
  const pathPairs = [];

  const pushCenterlinePairs = (pts, y, out) => {
    for (let i = 0; i < pts.length - 1; i += 1) {
      const a = pts[i];
      const b = pts[i + 1];
      out.push(a[0], y, -a[1], b[0], y, -b[1]);
    }
  };

  const pushOffsetPairs = (pts, half, y, out) => {
    if (pts.length < 2) return;
    const left = [];
    const right = [];
    for (let i = 0; i < pts.length; i += 1) {
      const p = pts[i];
      const p0 = pts[Math.max(0, i - 1)];
      const p1 = pts[Math.min(pts.length - 1, i + 1)];
      let tx = p1[0] - p0[0];
      let ty = p1[1] - p0[1];
      const tl = Math.hypot(tx, ty) || 1;
      tx /= tl;
      ty /= tl;
      const nx = -ty;
      const ny = tx;
      left.push([p[0] + nx * half, p[1] + ny * half]);
      right.push([p[0] - nx * half, p[1] - ny * half]);
    }
    pushCenterlinePairs(left, y, out);
    pushCenterlinePairs(right, y, out);
  };

  segs.forEach((s) => {
    const pts = s.coords || [];
    if (pts.length < 2) return;
    const hw = String(s.highway || "");
    const isPath = /footway|path|cycleway|steps|track|pedestrian|crossing/.test(hw);
    if (isPath) {
      // Dual edge for longer walks (reads as a path), centerline for stubs.
      let len = 0;
      for (let i = 1; i < pts.length; i += 1) {
        len += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
      }
      if (len >= 12 && pts.length >= 3) {
        pushOffsetPairs(pts, Math.max(0.7, (s.width_m || 2.4) * 0.4), 0.14, pathPairs);
      } else {
        pushCenterlinePairs(pts, 0.14, pathPairs);
      }
      return;
    }
    const half = Math.max(0.7, (s.width_m || 4) * 0.45);
    pushOffsetPairs(pts, half, 0.08, roadPairs);
  });

  const addBatch = (pairs, mat) => {
    if (!pairs.length) return;
    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position", new THREE.Float32BufferAttribute(pairs, 3));
    const lines = new THREE.LineSegments(geom, mat);
    lines.renderOrder = 0;
    group.add(lines);
  };
  addBatch(roadPairs, roadMat);
  addBatch(pathPairs, pathMat);
  return group;
}

/** Skip LandsD podium decks that act as a solid campus “ground plate”. */
function isGroundDeckSlab(b, ring) {
  const h = Number(b.height_m) || 0;
  const area = Number(b.area_m2) || 0;
  const bt = String(b.block_type || "");
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const p of ring) {
    minX = Math.min(minX, p[0]);
    maxX = Math.max(maxX, p[0]);
    minY = Math.min(minY, p[1]);
    maxY = Math.max(maxY, p[1]);
  }
  const span = Math.max(maxX - minX, maxY - minY);
  // Huge low podium = hard base that buries trees/paths (e.g. PolyU deck ~64k m²).
  if (bt === "Podium" && h <= 20 && (area >= 12000 || span >= 180)) return true;
  if (bt === "Podium" && h <= 16 && area >= 3500) return true;
  if (bt === "Podium" && h <= 10 && area >= 2500) return true;
  if (h <= 6 && (area >= 8000 || span >= 200)) return true;
  // Very short wide footprints read as ground decks, not buildings.
  if (h <= 6 && area >= 1000 && span >= 70) return true;
  return false;
}

/** Ray-cast point-in-polygon (local x/y metres). */
function pointInRing(x, y, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0];
    const yi = ring[i][1];
    const xj = ring[j][0];
    const yj = ring[j][1];
    const hit =
      yi > y !== yj > y &&
      x < ((xj - xi) * (y - yi)) / (yj - yi + 1e-12) + xi;
    if (hit) inside = !inside;
  }
  return inside;
}

function ringCentroid(ring) {
  let sx = 0;
  let sy = 0;
  for (const p of ring) {
    sx += p[0];
    sy += p[1];
  }
  const n = ring.length || 1;
  return [sx / n, sy / n];
}

/** True if building footprint sits in the main PolyU campus outline. */
function isPolyUCampusBuilding(ring, campusRings) {
  if (!campusRings?.length || ring.length < 3) return false;
  const [cx, cy] = ringCentroid(ring);
  // rings[0] is the main campus polygon; ignore far satellite rings.
  return pointInRing(cx, cy, campusRings[0]);
}

/** LandsD massing — soft grey context; PolyU campus slightly warmer. */
function buildBuildings(buildingsPayload, campusRings) {
  const group = new THREE.Group();
  const list = buildingsPayload?.buildings || [];

  // Context (outside PolyU): cool light grey.
  const wallMat = new THREE.MeshStandardMaterial({
    color: 0xc8c6c2,
    roughness: 0.92,
    metalness: 0.02,
    transparent: true,
    opacity: 0.98,
    depthWrite: true,
    flatShading: true,
  });
  const roofMat = new THREE.MeshStandardMaterial({
    color: 0xb8b6b2,
    roughness: 0.9,
    metalness: 0.02,
    transparent: true,
    opacity: 0.98,
    side: THREE.DoubleSide,
    flatShading: true,
  });
  // PolyU campus: soft cool slate-blue — distinct from taupe ground + grey context.
  const wallMatCampus = new THREE.MeshStandardMaterial({
    color: 0xa8b4c0,
    roughness: 0.9,
    metalness: 0.02,
    transparent: true,
    opacity: 0.98,
    depthWrite: true,
    flatShading: true,
  });
  const roofMatCampus = new THREE.MeshStandardMaterial({
    color: 0x96a4b2,
    roughness: 0.88,
    metalness: 0.02,
    transparent: true,
    opacity: 0.98,
    side: THREE.DoubleSide,
    flatShading: true,
  });
  const edgeMat = new THREE.LineBasicMaterial({
    color: 0x6a6864,
    transparent: true,
    opacity: 0.45,
  });
  const edgeMatCampus = new THREE.LineBasicMaterial({
    color: 0x5a6878,
    transparent: true,
    opacity: 0.5,
  });

  list.forEach((b) => {
    const ring = b.ring || [];
    if (ring.length < 3) return;
    if (isGroundDeckSlab(b, ring)) return;
    const onCampus = isPolyUCampusBuilding(ring, campusRings);
    const wall = onCampus ? wallMatCampus : wallMat;
    const roof = onCampus ? roofMatCampus : roofMat;
    const edge = onCampus ? edgeMatCampus : edgeMat;
    const h = Math.max(2.5, b.height_m || 2.5);
    const base = Math.max(0, Number(b.base_m) || 0);
    const shape = new THREE.Shape();
    shape.moveTo(ring[0][0], ring[0][1]);
    for (let i = 1; i < ring.length; i += 1) shape.lineTo(ring[i][0], ring[i][1]);
    shape.closePath();

    const geom = new THREE.ExtrudeGeometry(shape, {
      depth: h,
      bevelEnabled: false,
      curveSegments: 1,
    });
    geom.rotateX(-Math.PI / 2);
    geom.translate(0, base, 0);
    geom.computeVertexNormals();

    const wallMesh = new THREE.Mesh(geom, wall);
    // Cast onto ground only — receiving shadows on buildings causes stripe acne.
    wallMesh.castShadow = true;
    wallMesh.receiveShadow = false;
    group.add(wallMesh);

    const roofGeom = new THREE.ShapeGeometry(shape);
    roofGeom.rotateX(-Math.PI / 2);
    roofGeom.translate(0, base + h + 0.04, 0);
    roofGeom.computeVertexNormals();
    const roofMesh = new THREE.Mesh(roofGeom, roof);
    roofMesh.castShadow = true;
    roofMesh.receiveShadow = false;
    group.add(roofMesh);

    const edges = new THREE.EdgesGeometry(geom, 12);
    const edgeLines = new THREE.LineSegments(edges, edge);
    edgeLines.renderOrder = 3;
    group.add(edgeLines);
  });
  return group;
}

/** Measured LAZ crowns as green point clouds (real extent for shadows later). */
function buildLazCrownPoints(meta, xyzF32) {
  const group = new THREE.Group();
  const n = Math.floor(xyzF32.length / 3);
  if (!n) return group;
  const positions = new Float32Array(n * 3);
  const colors = new Float32Array(n * 3);
  // xyz local: x east, y north, z up → Three: x, y=up, z=-north
  for (let i = 0; i < n; i += 1) {
    const x = xyzF32[i * 3];
    const yN = xyzF32[i * 3 + 1];
    const zU = xyzF32[i * 3 + 2];
    positions[i * 3] = x;
    positions[i * 3 + 1] = zU;
    positions[i * 3 + 2] = -yN;
    const t = Math.min(1, Math.max(0, (zU - 2) / 18));
    colors[i * 3] = 0.08 + 0.12 * (1 - t);
    colors[i * 3 + 1] = 0.42 + 0.4 * t;
    colors[i * 3 + 2] = 0.12 + 0.08 * (1 - t);
  }
  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geom.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  group.add(
    new THREE.Points(
      geom,
      new THREE.PointsMaterial({
        size: 1.35,
        vertexColors: true,
        sizeAttenuation: true,
        transparent: true,
        opacity: 0.88,
        depthWrite: false,
      })
    )
  );
  group.userData.n_crowns = meta?.n_trees || 0;
  group.userData.n_points = n;
  group.userData.source = "laz_points";
  return group;
}

/** LAD canopy voxels from the CFD drag package (shows where vegetation slows wind). */
function buildLadCanopyOverlay(treesPayload) {
  const group = new THREE.Group();
  const canopy = treesPayload?.canopy || {};
  const xyz = canopy.xyz || [];
  const lai = canopy.lai || [];
  if (!xyz.length) return group;
  let laiMax = 1;
  for (let i = 0; i < lai.length; i += 1) laiMax = Math.max(laiMax, lai[i] || 0);
  const positions = new Float32Array(xyz.length * 3);
  const colors = new Float32Array(xyz.length * 3);
  for (let i = 0; i < xyz.length; i += 1) {
    const p = xyz[i];
    positions[i * 3] = p[0];
    positions[i * 3 + 1] = p[2];
    positions[i * 3 + 2] = -p[1];
    const u = Math.min(1, (lai[i] || 0.2) / laiMax);
    colors[i * 3] = 0.05 + 0.1 * (1 - u);
    colors[i * 3 + 1] = 0.55 + 0.4 * u;
    colors[i * 3 + 2] = 0.12;
  }
  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geom.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  group.add(
    new THREE.Points(
      geom,
      new THREE.PointsMaterial({
        size: 2.8,
        vertexColors: true,
        sizeAttenuation: true,
        transparent: true,
        opacity: 0.55,
        depthWrite: false,
      })
    )
  );
  group.userData.source = "lad_drag";
  group.userData.n_points = xyz.length;
  return group;
}

/** Thin box outline of the CFD UVW domain (where wind tracers can exist). */
function buildWindDomainOutline(Lx, Ly) {
  const y = 0.35;
  const pts = [
    new THREE.Vector3(0, y, 0),
    new THREE.Vector3(Lx, y, 0),
    new THREE.Vector3(Lx, y, -Ly),
    new THREE.Vector3(0, y, -Ly),
    new THREE.Vector3(0, y, 0),
  ];
  const geom = new THREE.BufferGeometry().setFromPoints(pts);
  return new THREE.Line(
    geom,
    new THREE.LineBasicMaterial({
      color: 0x5ec8a8,
      transparent: true,
      opacity: 0.45,
    })
  );
}

/** LAZ crowns as simple tree meshes (trunk + cone / layered canopy), not balloon spheres. */
function buildTrees(treesPayload) {
  const group = new THREE.Group();
  if (!treesPayload) return group;

  const trunkMat = new THREE.MeshStandardMaterial({
    color: 0x5c3a1e,
    roughness: 0.95,
    metalness: 0,
  });
  const foliageMat = new THREE.MeshStandardMaterial({
    color: 0x2a9d4a,
    emissive: 0x062412,
    emissiveIntensity: 0.18,
    roughness: 0.88,
    metalness: 0,
    flatShading: true,
  });
  const foliageDarkMat = new THREE.MeshStandardMaterial({
    color: 0x1f7a38,
    emissive: 0x04180c,
    emissiveIntensity: 0.12,
    roughness: 0.92,
    metalness: 0,
    flatShading: true,
  });
  const foliageLiteMat = new THREE.MeshStandardMaterial({
    color: 0x3db85a,
    emissive: 0x083018,
    emissiveIntensity: 0.14,
    roughness: 0.85,
    metalness: 0,
    flatShading: true,
  });

  // Shared unit geometries (scaled per tree).
  const trunkGeom = new THREE.CylinderGeometry(0.35, 0.55, 1, 6);
  const coneGeom = new THREE.ConeGeometry(1, 1, 8); // tip up — conifer / pointed canopy
  const lobeGeom = new THREE.IcosahedronGeometry(1, 0); // faceted broadleaf lobes

  const crowns = treesPayload.crowns || [];
  crowns.forEach((t, idx) => {
    const h = Math.max(4, t.height_m || 6);
    const r = Math.max(1.6, (t.radius_m || 2) * 1.15);
    const z0 = t.z0 || 0;
    const trunkH = Math.min(3.4, Math.max(1.4, h * 0.32));
    const crownH = Math.max(2.8, h - trunkH * 0.55);
    const tree = new THREE.Group();
    tree.position.set(t.x, z0, -t.y);

    const trunk = new THREE.Mesh(trunkGeom, trunkMat);
    trunk.scale.set(Math.max(0.7, r * 0.18), trunkH, Math.max(0.7, r * 0.18));
    trunk.position.y = trunkH * 0.5;
    tree.add(trunk);

    // Tall/narrow → cone layers; wider → stacked broadleaf lobes (still tree-shaped).
    const conical = r / crownH < 0.55 || idx % 3 === 0;
    if (conical) {
      const tiers = 3;
      for (let k = 0; k < tiers; k += 1) {
        const u = k / (tiers - 1);
        const cone = new THREE.Mesh(coneGeom, k === tiers - 1 ? foliageLiteMat : foliageMat);
        const tierR = r * (1.05 - 0.28 * u);
        const tierH = crownH * (0.42 - 0.06 * k);
        cone.scale.set(tierR, tierH, tierR);
        cone.position.y = trunkH + crownH * (0.22 + 0.28 * u);
        tree.add(cone);
      }
    } else {
      // Broadleaf: 3 faceted lobes, wide base → smaller top (not one balloon).
      const layers = [
        { y: 0.28, sx: 1.05, sy: 0.55, mat: foliageDarkMat },
        { y: 0.55, sx: 0.88, sy: 0.5, mat: foliageMat },
        { y: 0.78, sx: 0.62, sy: 0.42, mat: foliageLiteMat },
      ];
      layers.forEach((layer) => {
        const lobe = new THREE.Mesh(lobeGeom, layer.mat);
        lobe.scale.set(r * layer.sx, crownH * layer.sy, r * layer.sx);
        lobe.position.y = trunkH + crownH * layer.y;
        lobe.rotation.y = (idx % 5) * 0.7;
        tree.add(lobe);
      });
    }

    group.add(tree);
  });

  // Soft LAD underlay — keep subtle so solid tree meshes stay the main read.
  const canopy = treesPayload.canopy || {};
  const xyz = canopy.xyz || [];
  const lai = canopy.lai || [];
  if (xyz.length) {
    const positions = new Float32Array(xyz.length * 3);
    const colors = new Float32Array(xyz.length * 3);
    let laiMax = 1;
    for (let i = 0; i < lai.length; i += 1) laiMax = Math.max(laiMax, lai[i] || 0);
    for (let i = 0; i < xyz.length; i += 1) {
      const p = xyz[i];
      positions[i * 3] = p[0];
      positions[i * 3 + 1] = p[2];
      positions[i * 3 + 2] = -p[1];
      const u = Math.min(1, (lai[i] || 0.2) / laiMax);
      colors[i * 3] = 0.1 + 0.12 * (1 - u);
      colors[i * 3 + 1] = 0.45 + 0.35 * u;
      colors[i * 3 + 2] = 0.14;
    }
    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geom.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    group.add(
      new THREE.Points(
        geom,
        new THREE.PointsMaterial({
          size: 2.2,
          vertexColors: true,
          sizeAttenuation: true,
          transparent: true,
          opacity: 0.35,
          depthWrite: false,
        })
      )
    );
  }
  return group;
}

function buildCampusBoundary(boundaryPayload) {
  const group = new THREE.Group();
  const rings = boundaryPayload?.rings || [];
  const mat = new THREE.LineBasicMaterial({
    color: 0x7ec8ff,
    transparent: true,
    opacity: 0.55,
  });
  rings.forEach((ring) => {
    if (!ring || ring.length < 3) return;
    const pts = ring.map(([x, y]) => new THREE.Vector3(x, 0.4, -y));
    pts.push(pts[0].clone());
    const geom = new THREE.BufferGeometry().setFromPoints(pts);
    group.add(new THREE.Line(geom, mat));
  });
  return group;
}

/** Local CFD (x east, y north, z up) → Three.js (x, y up, z = -north). */
function toThree(x, yNorth, zUp, out, o) {
  out[o] = x;
  out[o + 1] = zUp;
  out[o + 2] = -yNorth;
}

/** Cool→warm ramp for air-temperature (blue → yellow → orange → red). */
function airTempColor(t01, out) {
  const t = Math.min(1, Math.max(0, t01));
  if (t < 0.33) {
    const u = t / 0.33;
    out.setRGB(0.12 + 0.2 * u, 0.4 + 0.45 * u, 0.92 - 0.35 * u);
  } else if (t < 0.66) {
    const u = (t - 0.33) / 0.33;
    out.setRGB(0.32 + 0.6 * u, 0.85 - 0.15 * u, 0.57 - 0.45 * u);
  } else {
    const u = (t - 0.66) / 0.34;
    out.setRGB(0.92 + 0.06 * u, 0.7 - 0.55 * u, 0.12 - 0.08 * u);
  }
  return out;
}

function airTempRange(stationsLocal) {
  const temps = stationsLocal.map((s) => s.temp_c);
  let tMin = Math.min(...temps);
  let tMax = Math.max(...temps);
  if (tMax - tMin < 0.4) {
    tMin -= 0.5;
    tMax += 0.5;
  }
  return { tMin, tMax };
}

/** Map °C → 0..1 using the fixed HK display scale. */
function airTempT01(tempC) {
  return (Number(tempC) - AIR_TEMP_COLOR_MIN_C) / (AIR_TEMP_COLOR_MAX_C - AIR_TEMP_COLOR_MIN_C);
}

/** Inverse-distance weighting of HKO AWS air temperature at a local (x east, y north) point. */
function idwAirTemp(x, y, stationsLocal, power = 2) {
  let wSum = 0;
  let tSum = 0;
  for (const s of stationsLocal) {
    const d2 = (x - s.x) * (x - s.x) + (y - s.y) * (y - s.y);
    const w = 1 / Math.max(d2, 25) ** (power / 2);
    wSum += w;
    tSum += w * s.temp_c;
  }
  return wSum > 0 ? tSum / wSum : null;
}

function addAirTempStationMarkers(group, stationsLocal, heightM) {
  const markerMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
  const markerGeom = new THREE.SphereGeometry(6, 12, 10);
  for (const s of stationsLocal) {
    const m = new THREE.Mesh(markerGeom, markerMat.clone());
    m.material.color.set(s.place === "King's Park" ? 0xffe066 : 0xffffff);
    m.position.set(s.x, heightM + 4, -s.y);
    m.userData.place = s.place;
    m.userData.temp_c = s.temp_c;
    group.add(m);
  }
}

/**
 * Pedestrian / roadside air temp: colour road + footpath centre/edges by HKO IDW
 * at ~1.2 m AGL. Preferred long-term view for HK-wide expansion (network-first).
 */
function buildAirTempRoadsGroup(
  roadsPayload,
  stationsLocal,
  heightM = HKO_AIR_TEMP_HEIGHT_M,
  withMarkers = true
) {
  const group = new THREE.Group();
  group.name = "hko-air-temp-roads";
  if (!stationsLocal?.length || !roadsPayload?.segments?.length) return group;

  const { tMin, tMax } = airTempRange(stationsLocal);
  const tmpA = new THREE.Color();
  const tmpB = new THREE.Color();
  const positions = [];
  const colors = [];
  const indices = [];

  const pushRibbon = (pts, half, y) => {
    if (pts.length < 2) return;
    for (let i = 0; i < pts.length - 1; i += 1) {
      const a = pts[i];
      const b = pts[i + 1];
      let tx = b[0] - a[0];
      let ty = b[1] - a[1];
      const tl = Math.hypot(tx, ty) || 1;
      tx /= tl;
      ty /= tl;
      const nx = -ty * half;
      const ny = tx * half;
      const ta = idwAirTemp(a[0], a[1], stationsLocal);
      const tb = idwAirTemp(b[0], b[1], stationsLocal);
      if (ta == null || tb == null) continue;
      airTempColor(airTempT01(ta), tmpA);
      airTempColor(airTempT01(tb), tmpB);
      const base = positions.length / 3;
      // Quad: aL, aR, bR, bL
      positions.push(a[0] + nx, y, -(a[1] + ny));
      colors.push(tmpA.r, tmpA.g, tmpA.b);
      positions.push(a[0] - nx, y, -(a[1] - ny));
      colors.push(tmpA.r, tmpA.g, tmpA.b);
      positions.push(b[0] - nx, y, -(b[1] - ny));
      colors.push(tmpB.r, tmpB.g, tmpB.b);
      positions.push(b[0] + nx, y, -(b[1] + ny));
      colors.push(tmpB.r, tmpB.g, tmpB.b);
      indices.push(base, base + 1, base + 2, base, base + 2, base + 3);
    }
  };

  // Slightly above base road lines so temp colour reads clearly.
  const yRoad = Math.max(0.35, heightM * 0.4);
  const yPath = Math.max(0.42, heightM * 0.5);

  for (const s of roadsPayload.segments) {
    const pts = s.coords || [];
    if (pts.length < 2) continue;
    const hw = String(s.highway || "");
    const isPath = /footway|path|cycleway|steps|track|pedestrian|crossing/.test(hw);
    if (isPath) {
      pushRibbon(pts, Math.max(1.4, (s.width_m || 2.4) * 0.55), yPath);
      continue;
    }
    pushRibbon(pts, Math.max(2.2, (s.width_m || 4) * 0.55), yRoad);
  }

  if (positions.length && indices.length) {
    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geom.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
    geom.setIndex(indices);
    const mesh = new THREE.Mesh(
      geom,
      new THREE.MeshBasicMaterial({
        vertexColors: true,
        transparent: true,
        opacity: 0.92,
        depthWrite: false,
        side: THREE.DoubleSide,
      })
    );
    mesh.renderOrder = 4;
    group.add(mesh);
  }

  if (withMarkers) addAirTempStationMarkers(group, stationsLocal, heightM);
  group.userData = {
    tMin,
    tMax,
    colorMin: AIR_TEMP_COLOR_MIN_C,
    colorMax: AIR_TEMP_COLOR_MAX_C,
    nStations: stationsLocal.length,
    nSegments: indices.length / 6,
    height_m_agl: heightM,
    mode: "roads",
  };
  return group;
}

/**
 * Optional full-area IDW carpet (screen ≈ 1.2 m AGL). Supporting view only —
 * not the HK-wide product default (station interpolation, not CFD thermal).
 */
function buildAirTempHeatmapGroup(
  stationsLocal,
  bounds,
  heightM = HKO_AIR_TEMP_HEIGHT_M,
  withMarkers = true
) {
  const group = new THREE.Group();
  group.name = "hko-air-temp-area";
  if (!stationsLocal?.length || !bounds) return group;

  const { x0, y0, x1, y1 } = bounds;
  const width = Math.max(40, x1 - x0);
  const height = Math.max(40, y1 - y0);
  const res = 96;
  const canvas = document.createElement("canvas");
  canvas.width = res;
  canvas.height = res;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  const img = ctx.createImageData(res, res);
  const { tMin, tMax } = airTempRange(stationsLocal);
  const tmp = new THREE.Color();
  // Strong colour near AWS; fade out beyond this so far PolyU fringes are not a solid mid-green slab.
  const fadeFullM = 700;
  const fadeOutM = 2200;

  for (let j = 0; j < res; j += 1) {
    for (let i = 0; i < res; i += 1) {
      const x = x0 + ((i + 0.5) / res) * width;
      const y = y1 - ((j + 0.5) / res) * height; // canvas y down
      let nearest = Infinity;
      for (const s of stationsLocal) {
        const d2 = (x - s.x) * (x - s.x) + (y - s.y) * (y - s.y);
        nearest = Math.min(nearest, Math.sqrt(d2));
      }
      const t = idwAirTemp(x, y, stationsLocal);
      airTempColor(airTempT01(t ?? tMin), tmp);
      let alpha = 0;
      if (nearest <= fadeFullM) alpha = 160;
      else if (nearest < fadeOutM) {
        alpha = Math.round(160 * (1 - (nearest - fadeFullM) / (fadeOutM - fadeFullM)));
      }
      const o = (j * res + i) * 4;
      img.data[o] = Math.round(tmp.r * 255);
      img.data[o + 1] = Math.round(tmp.g * 255);
      img.data[o + 2] = Math.round(tmp.b * 255);
      img.data[o + 3] = alpha;
    }
  }
  ctx.putImageData(img, 0, 0);

  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.magFilter = THREE.LinearFilter;
  tex.minFilter = THREE.LinearFilter;
  const plane = new THREE.Mesh(
    new THREE.PlaneGeometry(width, height),
    new THREE.MeshBasicMaterial({
      map: tex,
      transparent: true,
      opacity: 0.72,
      depthWrite: false,
      side: THREE.DoubleSide,
    })
  );
  plane.rotation.x = -Math.PI / 2;
  plane.position.set(0.5 * (x0 + x1), heightM, -0.5 * (y0 + y1));
  plane.renderOrder = 2;
  group.add(plane);

  if (withMarkers) addAirTempStationMarkers(group, stationsLocal, heightM);

  group.userData = {
    tMin,
    tMax,
    colorMin: AIR_TEMP_COLOR_MIN_C,
    colorMax: AIR_TEMP_COLOR_MAX_C,
    nStations: stationsLocal.length,
    height_m_agl: heightM,
    mode: "area",
  };
  return group;
}

function formatStamp(ts) {
  if (!ts) return "latest package";
  return String(ts).replace("T", " ").slice(0, 16);
}

/** Hong Kong civil time → Date (UTC+8). */
function hkDateFromParts(dateStr, minutesOfDay) {
  const [y, m, d] = dateStr.split("-").map(Number);
  const hh = Math.floor(minutesOfDay / 60);
  const mm = minutesOfDay % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return new Date(`${y}-${pad(m)}-${pad(d)}T${pad(hh)}:${pad(mm)}:00+08:00`);
}

function todayHkDateStr() {
  const now = new Date();
  // Format calendar day in HKT
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Hong_Kong",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return fmt.format(now); // YYYY-MM-DD
}

function hkMinutesNow() {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Hong_Kong",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date());
  const hh = Number(parts.find((p) => p.type === "hour")?.value || 12);
  const mm = Number(parts.find((p) => p.type === "minute")?.value || 0);
  return hh * 60 + mm;
}

/**
 * SunCalc v2 returns altitude/azimuth in **degrees** (v1 was radians).
 * Normalize to radians for trig; keep degree copies for UI.
 */
function sunPositionRad(date) {
  const pos = SunCalc.getPosition(date, POLYU_LAT, POLYU_LON);
  let alt = Number(pos.altitude);
  let az = Number(pos.azimuth);
  // Heuristic: values beyond ±90° alt or ±180° az are degrees (v2).
  const inDegrees = Math.abs(alt) > Math.PI / 2 + 0.05 || Math.abs(az) > Math.PI + 0.05;
  if (inDegrees) {
    alt *= Math.PI / 180;
    az *= Math.PI / 180;
  }
  return { altitude: alt, azimuth: az };
}

/**
 * Sun unit vector toward the sun in viewer frame (x east, y up, z = -north).
 * Azimuth from south toward west (SunCalc convention).
 */
function sunDirectionViewer(date) {
  const { altitude: alt, azimuth: az } = sunPositionRad(date);
  const ch = Math.cos(alt);
  const east = -Math.sin(az) * ch;
  const north = -Math.cos(az) * ch;
  const up = Math.sin(alt);
  const dir = new THREE.Vector3(east, up, -north);
  if (dir.lengthSq() < 1e-8) {
    return { dir: new THREE.Vector3(0, 1, 0), altitude: alt, azimuth: az };
  }
  dir.normalize();
  return { dir, altitude: alt, azimuth: az };
}

function solarDayBoundsHk(dateStr) {
  const noon = hkDateFromParts(dateStr, 12 * 60);
  const times = SunCalc.getTimes(noon, POLYU_LAT, POLYU_LON);
  const toMinutes = (dt) => {
    if (!dt || Number.isNaN(dt.getTime())) return null;
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Hong_Kong",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).formatToParts(dt);
    const hh = Number(parts.find((p) => p.type === "hour")?.value || 0);
    const mm = Number(parts.find((p) => p.type === "minute")?.value || 0);
    return hh * 60 + mm;
  };
  return {
    sunriseMin: toMinutes(times.sunrise),
    sunsetMin: toMinutes(times.sunset),
  };
}

function enableMeshShadows(root, { cast = true, receive = true } = {}) {
  if (!root) return;
  root.traverse((obj) => {
    if (obj.isMesh) {
      obj.castShadow = cast;
      obj.receiveShadow = receive;
    }
  });
}

function formatHm(minutesOfDay) {
  const hh = Math.floor(minutesOfDay / 60) % 24;
  const mm = minutesOfDay % 60;
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}

export default function WindFlowViewer() {
  const wrapRef = useRef(null);
  const solarApiRef = useRef(null);
  const airTempApiRef = useRef(null);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const [meta, setMeta] = useState(null);
  const [shadowDate, setShadowDate] = useState(todayHkDateStr);
  // Default near midday so shadows are visible (full-day slider is mostly night).
  const [shadowMinutes, setShadowMinutes] = useState(12 * 60);
  const [shadowPlaying, setShadowPlaying] = useState(false);
  const [dayBounds, setDayBounds] = useState({ sunriseMin: 6 * 60, sunsetMin: 18 * 60 });
  const [solarInfo, setSolarInfo] = useState({
    altitudeDeg: 0,
    azimuthDeg: 0,
    aboveHorizon: false,
  });
  const [hkoAirTemp, setHkoAirTemp] = useState(null);
  /** Live deploy: whole-area IDW only (road temp kept in code, off by default). */
  const [showAirTempRoads, setShowAirTempRoads] = useState(false);
  const [showAirTempArea, setShowAirTempArea] = useState(true);
  const [airTempLayerMeta, setAirTempLayerMeta] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function pullAirTemp() {
      const res = await getHkoAirTemp("King's Park");
      if (cancelled) return;
      if (res.ok) setHkoAirTemp(res.data);
    }
    pullAirTemp();
    const id = window.setInterval(pullAirTemp, HKO_AIR_TEMP_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    setDayBounds(solarDayBoundsHk(shadowDate));
  }, [shadowDate]);

  useEffect(() => {
    solarApiRef.current?.setTime?.(shadowDate, shadowMinutes);
  }, [shadowDate, shadowMinutes]);

  useEffect(() => {
    const info =
      airTempApiRef.current?.setLayer?.(hkoAirTemp, {
        roads: showAirTempRoads,
        area: showAirTempArea,
      }) || null;
    setAirTempLayerMeta(info);
  }, [hkoAirTemp, showAirTempRoads, showAirTempArea, status, meta?.updated_at]);

  useEffect(() => {
    if (!shadowPlaying) return undefined;
    const id = window.setInterval(() => {
      setShadowMinutes((m) => {
        const start = dayBounds.sunriseMin ?? 6 * 60;
        const end = dayBounds.sunsetMin ?? 18 * 60;
        const next = m + 3;
        if (next > end) return start;
        if (next < start) return start;
        return next;
      });
    }, 80);
    return () => window.clearInterval(id);
  }, [shadowPlaying, dayBounds]);

  useEffect(() => {
    let disposed = false;
    let raf = 0;
    let pollTimer = 0;
    let hourTimer = 0;
    const wrap = wrapRef.current;
    if (!wrap) return undefined;

    const scene = new THREE.Scene();
    // Soft clay-render atmosphere (not pure black void).
    scene.background = new THREE.Color(0x2a2622);
    scene.fog = new THREE.FogExp2(0x2a2622, 0.00042);
    const camera = new THREE.PerspectiveCamera(42, 1, 1, 5000);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.12;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    wrap.appendChild(renderer.domElement);

    // Natural taupe / mink ground (clay-model look) — flat terrain only, not a podium slab.
    const ground = new THREE.Mesh(
      new THREE.CircleGeometry(2200, 72),
      new THREE.MeshStandardMaterial({
        color: 0x8b7d6b,
        roughness: 0.96,
        metalness: 0.0,
        flatShading: true,
      })
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.02;
    ground.receiveShadow = true;
    scene.add(ground);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.28;
    controls.maxPolarAngle = Math.PI * 0.48;

    // Capture hook filled after solar + domain state exist (scripts/capture_dashboard_gifs.py).
    window.__CFD_SHADOW__ = { ready: false };

    scene.add(new THREE.HemisphereLight(0xb8cce0, 0x2a2218, 0.42));
    scene.add(new THREE.AmbientLight(0xdde6f2, 0.22));
    // Solar directional light — pose updated from SunCalc (ShadeMap-style).
    const sun = new THREE.DirectionalLight(0xfff1dc, 1.35);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.bias = -0.00035;
    sun.shadow.normalBias = 0.04;
    const shadowSpan = 520;
    sun.shadow.camera.left = -shadowSpan;
    sun.shadow.camera.right = shadowSpan;
    sun.shadow.camera.top = shadowSpan;
    sun.shadow.camera.bottom = -shadowSpan;
    sun.shadow.camera.near = 10;
    sun.shadow.camera.far = 2200;
    scene.add(sun);
    scene.add(sun.target);
    const fill = new THREE.DirectionalLight(0x7aa0c8, 0.28);
    fill.position.set(-200, 140, -160);
    scene.add(fill);
    const rim = new THREE.DirectionalLight(0xffc8a0, 0.14);
    rim.position.set(80, 60, -280);
    scene.add(rim);

    const solarFocus = new THREE.Vector3(200, 0, -200);
    let lastSolarDate = shadowDate;
    let lastSolarMinutes = shadowMinutes;
    function applySolarTime(dateStr, minutesOfDay) {
      lastSolarDate = dateStr;
      lastSolarMinutes = minutesOfDay;
      const when = hkDateFromParts(dateStr, minutesOfDay);
      const { dir, altitude, azimuth } = sunDirectionViewer(when);
      const above = altitude > 0.02;
      const dist = 900;
      sun.position.set(
        solarFocus.x + dir.x * dist,
        solarFocus.y + dir.y * dist,
        solarFocus.z + dir.z * dist
      );
      sun.target.position.copy(solarFocus);
      sun.target.updateMatrixWorld();
      sun.intensity = above ? 1.35 : 0.05;
      sun.castShadow = above;
      fill.intensity = above ? 0.28 : 0.45;
      if (!disposed) {
        setSolarInfo({
          altitudeDeg: (altitude * 180) / Math.PI,
          azimuthDeg: (((azimuth * 180) / Math.PI) % 360 + 360) % 360,
          aboveHorizon: above,
        });
      }
    }
    solarApiRef.current = {
      setTime: applySolarTime,
      setFocus: (x, yNorth) => {
        solarFocus.set(x, 0, -yNorth);
        applySolarTime(lastSolarDate, lastSolarMinutes);
      },
    };
    applySolarTime(lastSolarDate, lastSolarMinutes);

    function focusMetrics() {
      const fx0 = S?.focus?.x0;
      const fx1 = S?.focus?.x1;
      const fy0 = S?.focus?.y0;
      const fy1 = S?.focus?.y1;
      if (fx0 == null) return null;
      const cx = 0.5 * (fx0 + fx1);
      const cy = 0.5 * (fy0 + fy1);
      const cz = Math.min(42, (S.nz || 40) * (S.dz || 1) * 0.35);
      const span = Math.max(fx1 - fx0, fy1 - fy0, 380);
      return { cx, cy, cz, span };
    }

    function setOrbitCamera(azDeg, elevDeg, distScale = 1) {
      const m = focusMetrics();
      if (!m) return false;
      controls.autoRotate = false;
      controls.enableDamping = false;
      const elev = (Math.max(12, Math.min(58, elevDeg)) * Math.PI) / 180;
      const az = (azDeg * Math.PI) / 180;
      const dist = m.span * 0.82 * distScale;
      const target = new THREE.Vector3(m.cx, m.cz * 0.28, -m.cy);
      controls.target.copy(target);
      camera.position.set(
        target.x + dist * Math.cos(elev) * Math.sin(az),
        Math.max(32, target.y + dist * Math.sin(elev)),
        target.z + dist * Math.cos(elev) * Math.cos(az)
      );
      camera.lookAt(target);
      controls.update();
      return true;
    }

    Object.assign(window.__CFD_SHADOW__, {
      setPlanView() {
        const m = focusMetrics();
        if (!m) return false;
        controls.target.set(m.cx, m.cz * 0.45, -m.cy);
        camera.position.set(m.cx - m.span * 0.55, m.span * 0.48, -m.cy + m.span * 0.52);
        controls.autoRotate = false;
        controls.update();
        renderer.render(scene, camera);
        return true;
      },
      setOrbitView(azDeg, elevDeg, distScale = 1) {
        const ok = setOrbitCamera(azDeg, elevDeg, distScale);
        if (ok) renderer.render(scene, camera);
        return ok;
      },
      setAutoRotate(on) {
        controls.autoRotate = !!on;
      },
      setWindVisible(on) {
        const v = !!on;
        if (S.lines) S.lines.visible = v;
        if (S.heads) S.heads.visible = v;
      },
      setAirTempModes(modes) {
        return airTempApiRef.current?.setModes?.(modes) || null;
      },
      getAirTempDebug() {
        return airTempApiRef.current?.getDebug?.() || null;
      },
      setSolarTime(dateStr, minutesOfDay) {
        applySolarTime(String(dateStr), Number(minutesOfDay));
        renderer.render(scene, camera);
        return {
          altitudeDeg: (sun.position.y > solarFocus.y ? 1 : 0),
          aboveHorizon: sun.castShadow,
        };
      },
      getDayBounds(dateStr) {
        return solarDayBoundsHk(String(dateStr || lastSolarDate));
      },
      getSolarDate() {
        return lastSolarDate;
      },
      snapshotDataUrl(quality = 0.82) {
        renderer.render(scene, camera);
        return renderer.domElement.toDataURL("image/jpeg", quality);
      },
    });

    const resize = () => {
      const w = wrap.clientWidth || 800;
      const h = wrap.clientHeight || 500;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h, false);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);

    const clock = new THREE.Clock();
    const tmpColor = new THREE.Color();
    const tmpColorB = new THREE.Color();
    let buildingsGroup = null;
    let treesGroup = null;
    let ladGroup = null;
    let windDomainOutline = null;
    let airTempRoadsGroup = null;
    let airTempAreaGroup = null;
    let airTempPayloadCache = null;
    let airTempMode = { roads: false, area: true };
    let roadsPayloadCache = null;

    function disposeAirTempObject(obj) {
      if (!obj) return;
      scene.remove(obj);
      obj.traverse((child) => {
        child.geometry?.dispose?.();
        if (child.material) {
          if (Array.isArray(child.material)) child.material.forEach((m) => m.dispose?.());
          else {
            child.material.map?.dispose?.();
            child.material.dispose?.();
          }
        }
      });
    }

    function disposeAirTempGroups() {
      disposeAirTempObject(airTempRoadsGroup);
      disposeAirTempObject(airTempAreaGroup);
      airTempRoadsGroup = null;
      airTempAreaGroup = null;
      if (roadsGroup) roadsGroup.visible = true;
    }

    function localAirTempStations(tempPayload) {
      if (!tempPayload?.stations?.length || !S.origin_hk80 || !S.focus) return [];
      const [ox, oy] = S.origin_hk80;
      const cx = 0.5 * (S.focus.x0 + S.focus.x1);
      const cy = 0.5 * (S.focus.y0 + S.focus.y1);
      const localStations = [];
      for (const s of tempPayload.stations) {
        if (s.easting == null || s.northing == null) continue;
        const x = s.easting - ox;
        const y = s.northing - oy;
        if (Math.hypot(x - cx, y - cy) > HKO_TEMP_STATION_RADIUS_M) continue;
        localStations.push({
          place: s.place,
          temp_c: s.temp_c,
          x,
          y,
        });
      }
      return localStations;
    }

    function rebuildAirTempLayers() {
      disposeAirTempGroups();
      const wantRoads = !!airTempMode.roads;
      const wantArea = !!airTempMode.area;
      if (!wantRoads && !wantArea) return null;
      if (!airTempPayloadCache || !S.origin_hk80 || !S.focus) return null;

      const localStations = localAirTempStations(airTempPayloadCache);
      if (!localStations.length) return null;

      let metaOut = null;
      if (wantRoads && roadsPayloadCache) {
        airTempRoadsGroup = buildAirTempRoadsGroup(
          roadsPayloadCache,
          localStations,
          HKO_AIR_TEMP_HEIGHT_M,
          true
        );
        scene.add(airTempRoadsGroup);
        if (roadsGroup) roadsGroup.visible = false;
        metaOut = {
          tMin: airTempRoadsGroup.userData.tMin,
          tMax: airTempRoadsGroup.userData.tMax,
          colorMin: AIR_TEMP_COLOR_MIN_C,
          colorMax: AIR_TEMP_COLOR_MAX_C,
          nStations: airTempRoadsGroup.userData.nStations,
          nSegments: airTempRoadsGroup.userData.nSegments,
          height_m_agl: HKO_AIR_TEMP_HEIGHT_M,
          mode: "roads",
        };
      }

      if (wantArea) {
        const pad = 120;
        const xs = localStations.map((s) => s.x);
        const ys = localStations.map((s) => s.y);
        const bounds = {
          x0: Math.min(S.focus.x0 - pad, ...xs) - 60,
          y0: Math.min(S.focus.y0 - pad, ...ys) - 60,
          x1: Math.max(S.focus.x1 + pad, ...xs) + 60,
          y1: Math.max(S.focus.y1 + pad, ...ys) + 60,
        };
        airTempAreaGroup = buildAirTempHeatmapGroup(
          localStations,
          bounds,
          HKO_AIR_TEMP_HEIGHT_M,
          !wantRoads
        );
        scene.add(airTempAreaGroup);
        metaOut = {
          tMin: airTempAreaGroup.userData.tMin,
          tMax: airTempAreaGroup.userData.tMax,
          colorMin: AIR_TEMP_COLOR_MIN_C,
          colorMax: AIR_TEMP_COLOR_MAX_C,
          nStations: airTempAreaGroup.userData.nStations,
          height_m_agl: HKO_AIR_TEMP_HEIGHT_M,
          mode: wantRoads ? "roads+area" : "area",
        };
      }
      return metaOut;
    }

    function setAirTempLayer(tempPayload, modes) {
      airTempPayloadCache = tempPayload || null;
      if (modes && typeof modes === "object") {
        airTempMode = {
          roads: !!modes.roads,
          area: !!modes.area,
        };
      }
      return rebuildAirTempLayers();
    }

    function setAirTempModes(modes) {
      if (modes && typeof modes === "object") {
        airTempMode = {
          roads: !!modes.roads,
          area: !!modes.area,
        };
      }
      const info = rebuildAirTempLayers();
      if (!disposed) setAirTempLayerMeta(info);
      return info;
    }

    function getAirTempDebug() {
      return {
        mode: { ...airTempMode },
        hasPayload: !!airTempPayloadCache,
        nStationsPayload: airTempPayloadCache?.stations?.length || 0,
        hasRoadsPayload: !!roadsPayloadCache,
        nRoadSegments: roadsPayloadCache?.segments?.length || 0,
        roadsVisible: airTempRoadsGroup != null,
        areaVisible: airTempAreaGroup != null,
        meta: airTempRoadsGroup?.userData || airTempAreaGroup?.userData || null,
      };
    }

    airTempApiRef.current = {
      setLayer: setAirTempLayer,
      setModes: setAirTempModes,
      getDebug: getAirTempDebug,
    };
    let roadsGroup = null;
    let boundaryGroup = null;
    let pedPlane = null;
    let packageStamp = "";
    let treeCount = 0;

    const S = {
      u: null,
      v: null,
      w: null,
      solid: null,
      nx: 0,
      ny: 0,
      nz: 0,
      dx: 1,
      dz: 1,
      pos: null,
      hist: null,
      age: null,
      life: null,
      lines: null,
      heads: null,
      vmax: 5,
      focus: null,
      ready: false,
      nParticles: N_PARTICLES_BASE,
      trail: TRAIL_BASE,
      districtScale: false,
      edgeMarginM: EDGE_MARGIN_M,
    };

    function spawnOne(i) {
      const { nx, ny, nz, dx, dz, solid, pos, focus } = S;
      const kPed = Math.min(nz - 1, Math.max(0, Math.round(PED_Z_M / dz - 0.5)));
      // Spawn on the 1.5 m AGL plane inside the wind focus.
      const margin = Math.max(1, Math.ceil((S.edgeMarginM || EDGE_MARGIN_M) / dx));
      let i0 = margin;
      let j0 = margin;
      let i1 = Math.max(i0 + 1, nx - margin);
      let j1 = Math.max(j0 + 1, ny - margin);
      if (focus && Number.isFinite(focus.x0)) {
        i0 = Math.max(1, Math.floor(focus.x0 / dx) + 1);
        j0 = Math.max(1, Math.floor(focus.y0 / dx) + 1);
        i1 = Math.min(nx - 1, Math.ceil(focus.x1 / dx) - 1);
        j1 = Math.min(ny - 1, Math.ceil(focus.y1 / dx) - 1);
        if (i1 <= i0 + 2) {
          i0 = margin;
          i1 = Math.max(i0 + 1, nx - margin);
        }
        if (j1 <= j0 + 2) {
          j0 = margin;
          j1 = Math.max(j0 + 1, ny - margin);
        }
      }
      for (let tries = 0; tries < 100; tries += 1) {
        const ii = i0 + ((Math.random() * (i1 - i0)) | 0);
        const jj = j0 + ((Math.random() * (j1 - j0)) | 0);
        if (solid[idx3(ii, jj, kPed, ny, nz)]) continue;
        pos[i * 3] = (ii + Math.random()) * dx;
        pos[i * 3 + 1] = (jj + Math.random()) * dx;
        pos[i * 3 + 2] = PED_Z_M + (Math.random() - 0.5) * 0.2;
        return;
      }
      pos[i * 3] = (i0 + Math.random() * (i1 - i0)) * dx;
      pos[i * 3 + 1] = (j0 + Math.random() * (j1 - j0)) * dx;
      pos[i * 3 + 2] = PED_Z_M;
    }

    function disposeParticles() {
      if (S.lines) {
        scene.remove(S.lines);
        S.lines.geometry.dispose();
        S.lines.material.dispose();
        S.lines = null;
      }
      if (S.heads) {
        scene.remove(S.heads);
        S.heads.geometry.dispose();
        S.heads.material.dispose();
        S.heads = null;
      }
    }

    function initParticles() {
      disposeParticles();
      const n = S.nParticles || N_PARTICLES_BASE;
      const trail = S.trail || TRAIL_BASE;
      S.nParticles = n;
      S.trail = trail;
      S.pos = new Float32Array(n * 3);
      S.hist = new Float32Array(n * trail * 3);
      S.age = new Int16Array(n);
      S.life = new Int16Array(n);
      for (let i = 0; i < n; i += 1) {
        spawnOne(i);
        S.age[i] = (Math.random() * 50) | 0;
        S.life[i] = 55 + ((Math.random() * 70) | 0);
        for (let t = 0; t < trail; t += 1) {
          const o = (i * trail + t) * 3;
          S.hist[o] = S.pos[i * 3];
          S.hist[o + 1] = S.pos[i * 3 + 1];
          S.hist[o + 2] = S.pos[i * 3 + 2];
        }
      }

      const nSeg = n * (trail - 1);
      const lineGeom = new THREE.BufferGeometry();
      lineGeom.setAttribute("position", new THREE.BufferAttribute(new Float32Array(nSeg * 2 * 3), 3));
      lineGeom.setAttribute("color", new THREE.BufferAttribute(new Float32Array(nSeg * 2 * 3), 3));
      S.lines = new THREE.LineSegments(
        lineGeom,
        new THREE.LineBasicMaterial({
          vertexColors: true,
          transparent: true,
          opacity: S.districtScale ? 0.88 : 0.92,
          depthWrite: false,
        })
      );
      scene.add(S.lines);

      const headGeom = new THREE.BufferGeometry();
      headGeom.setAttribute("position", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
      headGeom.setAttribute("color", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
      // Larger heads when viewing Hung Hom from higher altitude.
      S.heads = new THREE.Points(
        headGeom,
        new THREE.PointsMaterial({
          size: S.districtScale ? 5.2 : 2.4,
          vertexColors: true,
          sizeAttenuation: true,
          transparent: true,
          opacity: 1,
          depthWrite: false,
        })
      );
      scene.add(S.heads);
    }

    function sampleUVW(x, y, z) {
      const { u, v, w, nx, ny, nz, dx, dz } = S;
      const ux = sampleGrid(u, nx, ny, nz, dx, dz, x, y, z);
      const uy = sampleGrid(v, nx, ny, nz, dx, dz, x, y, z);
      let uz = sampleGrid(w, nx, ny, nz, dx, dz, x, y, z);
      uz = Math.max(-2.2, Math.min(2.2, uz));
      return [ux, uy, uz];
    }

    function stepParticles(dt) {
      if (!S.ready || !S.lines || !S.heads) return;
      const { solid, nx, ny, nz, dx, dz, pos, hist, age, life, vmax, lines, heads } = S;
      const linePos = lines.geometry.getAttribute("position");
      const lineCol = lines.geometry.getAttribute("color");
      const headPos = heads.geometry.getAttribute("position");
      const headCol = heads.geometry.getAttribute("color");
      // One substep on district (2 was too heavy with thousands of tracers).
      const sub = S.districtScale ? 1 : 2;
      const h = dt / sub;

      const nP = S.nParticles || N_PARTICLES_BASE;
      const trail = S.trail || TRAIL_BASE;
      const edgeM = S.edgeMarginM || EDGE_MARGIN_M;
      for (let i = 0; i < nP; i += 1) {
        let x = pos[i * 3];
        let y = pos[i * 3 + 1];
        let z = pos[i * 3 + 2];
        let ux = 0;
        let uy = 0;
        let uz = 0;

        // Horizontal advection only at pedestrian / canopy level (1.5 m AGL).
        for (let s = 0; s < sub; s += 1) {
          const [u1, v1] = sampleUVW(x, y, PED_Z_M);
          if (sub === 1) {
            x += h * u1;
            y += h * v1;
            ux = u1;
            uy = v1;
          } else {
            const mx = x + 0.5 * h * u1;
            const my = y + 0.5 * h * v1;
            const [u2, v2] = sampleUVW(mx, my, PED_Z_M);
            x += h * u2;
            y += h * v2;
            ux = u2;
            uy = v2;
          }
          uz = 0;
        }
        z = PED_Z_M;

        pos[i * 3] = x;
        pos[i * 3 + 1] = y;
        pos[i * 3 + 2] = z;
        age[i] += 1;

        for (let t = 0; t < trail - 1; t += 1) {
          const a = (i * trail + t) * 3;
          const b = (i * trail + t + 1) * 3;
          hist[a] = hist[b];
          hist[a + 1] = hist[b + 1];
          hist[a + 2] = hist[b + 2];
        }
        const head = (i * trail + trail - 1) * 3;
        hist[head] = x;
        hist[head + 1] = y;
        hist[head + 2] = z;

        const ci = Math.min(nx - 1, Math.max(0, (x / dx) | 0));
        const cj = Math.min(ny - 1, Math.max(0, (y / dx) | 0));
        const ck = Math.min(nz - 1, Math.max(0, (z / dz) | 0));
        const Lx = nx * dx;
        const Ly = ny * dx;
        const eFade = edgeFade(x, y, Lx, Ly, edgeM) * focusFade(x, y, S.focus, edgeM);
        const dead =
          solid[idx3(ci, cj, ck, ny, nz)] ||
          age[i] > life[i] ||
          eFade < 0.05 ||
          x < 0 ||
          y < 0 ||
          x > Lx ||
          y > Ly;
        if (dead) {
          spawnOne(i);
          age[i] = 0;
          life[i] = 55 + ((Math.random() * 70) | 0);
          for (let t = 0; t < trail; t += 1) {
            const o = (i * trail + t) * 3;
            hist[o] = pos[i * 3];
            hist[o + 1] = pos[i * 3 + 1];
            hist[o + 2] = pos[i * 3 + 2];
          }
        }

        // Colour whole trail from head speed (avoids 2× sampleUVW per segment).
        turboColor(Math.hypot(ux, uy, uz) / vmax, tmpColor);
        const headEf = eFade;
        for (let t = 0; t < trail - 1; t += 1) {
          const seg = (i * (trail - 1) + t) * 6;
          const o0 = (i * trail + t) * 3;
          const o1 = (i * trail + t + 1) * 3;
          toThree(hist[o0], hist[o0 + 1], hist[o0 + 2], linePos.array, seg);
          toThree(hist[o1], hist[o1 + 1], hist[o1 + 2], linePos.array, seg + 3);
          const fade0 = (0.35 + 0.65 * (t / (trail - 1))) * headEf;
          const fade1 = (0.35 + 0.65 * ((t + 1) / (trail - 1))) * headEf;
          lineCol.array[seg] = tmpColor.r * fade0;
          lineCol.array[seg + 1] = tmpColor.g * fade0;
          lineCol.array[seg + 2] = tmpColor.b * fade0;
          lineCol.array[seg + 3] = tmpColor.r * fade1;
          lineCol.array[seg + 4] = tmpColor.g * fade1;
          lineCol.array[seg + 5] = tmpColor.b * fade1;
        }

        turboColor(Math.hypot(ux, uy, uz) / vmax, tmpColor);
        const ho = i * 3;
        toThree(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2], headPos.array, ho);
        const hf =
          edgeFade(pos[i * 3], pos[i * 3 + 1], Lx, Ly, edgeM) *
          focusFade(pos[i * 3], pos[i * 3 + 1], S.focus, edgeM);
        headCol.array[ho] = tmpColor.r * hf;
        headCol.array[ho + 1] = tmpColor.g * hf;
        headCol.array[ho + 2] = tmpColor.b * hf;
      }

      linePos.needsUpdate = true;
      lineCol.needsUpdate = true;
      headPos.needsUpdate = true;
      headCol.needsUpdate = true;
    }

    function applyWindPackage(wind) {
      const dom = wind.domain;
      S.origin_hk80 = Array.isArray(dom.origin_hk80)
        ? [Number(dom.origin_hk80[0]), Number(dom.origin_hk80[1])]
        : null;
      S.nx = dom.nx;
      S.ny = dom.ny;
      S.nz = dom.nz;
      S.dx = dom.dx_m;
      S.dz = dom.dz_m;
      S.u = decodeF16LE(wind.grid.u);
      S.v = decodeF16LE(wind.grid.v);
      S.w = decodeF16LE(wind.grid.w);
      S.solid = decodeU8(wind.grid.solid);
      // Full wind package extent (campus core, or Hung Hom district pad).
      const Lx = S.nx * S.dx;
      const Ly = S.ny * S.dx;
      const hunghom = !!dom.hunghom_district || !!dom.air_radius_extended;
      S.districtScale = hunghom;
      S.trail = hunghom ? TRAIL_DISTRICT : TRAIL_BASE;
      S.edgeMarginM = hunghom ? Math.max(80, Math.min(140, Math.max(Lx, Ly) * 0.04)) : EDGE_MARGIN_M;
      S.nParticles = particleCountForDomain(
        S.nx,
        S.ny,
        S.dx,
        wind.viz?.n_particles_default,
        hunghom
      );
      S.focus = {
        x0: 0,
        y0: 0,
        x1: Lx,
        y1: Ly,
        note: hunghom
          ? `Hung Hom district (~${Math.round(dom.radius_m || Math.max(Lx, Ly) * 0.5)} m radius)`
          : `PolyU boundary + ${WIND_FOCUS_PAD_M} m (CFD extent)`,
      };

      // Colour scale from 1.5 m AGL layer (tree / pedestrian height).
      const speeds = [];
      const fx0 = S.focus.x0;
      const fy0 = S.focus.y0;
      const fx1 = S.focus.x1;
      const fy1 = S.focus.y1;
      const kPed = Math.min(S.nz - 1, Math.max(0, Math.round(PED_Z_M / S.dz - 0.5)));
      for (let i = 0; i < S.nx; i += 2) {
        for (let j = 0; j < S.ny; j += 2) {
          const x = (i + 0.5) * S.dx;
          const y = (j + 0.5) * S.dx;
          if (x < fx0 || x > fx1 || y < fy0 || y > fy1) continue;
          const o = idx3(i, j, kPed, S.ny, S.nz);
          if (S.solid[o]) continue;
          speeds.push(Math.hypot(S.u[o], S.v[o], S.w[o]));
        }
      }
      speeds.sort((a, b) => a - b);
      const p98 = speeds.length ? speeds[Math.floor(speeds.length * 0.98)] : 5;
      const p50 = speeds.length ? speeds[Math.floor(speeds.length * 0.5)] : 3;
      const inletU = Number(wind.inlet?.u_ref_mps) || 4;
      const hint = Number(wind.viz?.vmax_hint_mps) || 0;
      // Avoid flat colour when freestream dominates: spread turbo across a real district range.
      S.vmax = Math.max(
        0.8,
        hint,
        p98,
        p50 * 1.8,
        inletU * 1.15,
        hunghom ? 6.0 : 0.8
      );

      initParticles();
      S.ready = true;

      if (pedPlane) {
        scene.remove(pedPlane);
        pedPlane.geometry.dispose();
        pedPlane.material.map?.dispose();
        pedPlane.material.dispose();
        pedPlane = null;
      }
      // No solid ground / comfort plate — paths + building footprints only.
      pedPlane = null;

      // Hung Hom: frame the full district. Campus-only: tighter core view.
      const cx = 0.5 * (fx0 + fx1);
      const cy = 0.5 * (fy0 + fy1);
      const cz = Math.min(42, S.nz * S.dz * 0.35);
      const span = Math.max(fx1 - fx0, fy1 - fy0, 380);
      if (S.districtScale) {
        controls.target.set(cx, 8, -cy);
        camera.position.set(cx - span * 0.35, span * 0.62, -cy + span * 0.72);
        controls.maxDistance = span * 2.5;
        controls.minDistance = 80;
      } else {
        controls.target.set(cx, cz * 0.45, -cy);
        camera.position.set(cx - span * 0.55, span * 0.48, -cy + span * 0.52);
      }
      controls.update();
      solarApiRef.current?.setFocus?.(cx, cy);

      if (windDomainOutline) {
        scene.remove(windDomainOutline);
        windDomainOutline.geometry?.dispose?.();
        windDomainOutline.material?.dispose?.();
        windDomainOutline = null;
      }

      packageStamp = wind.updated_at || wind.inlet?.timestamp || "";
      setMeta({
        ...(wind.inlet || {}),
        updated_at: wind.updated_at,
        n_trees: treeCount,
        vmax_mps: Number(S.vmax.toFixed(2)),
        wind_extent_m: [Number(Lx.toFixed(0)), Number(Ly.toFixed(0))],
        domain_label: S.districtScale ? "Hung Hom district" : "PolyU campus",
        n_particles: S.nParticles,
        radius_m: dom.radius_m || null,
      });
      setStatus("ready");
      setError("");
      if (window.__CFD_SHADOW__) window.__CFD_SHADOW__.ready = true;
    }

    async function loadLazTrees() {
      const [metaRes, binRes, solidMeta] = await Promise.all([
        getLazCrownsMeta(),
        getLazCrownsBin(),
        getSolidTreesMeta(),
      ]);
      if (disposed) return false;

      // Prefer solid LAZ meshes when available; else measured point crowns.
      let ok = false;
      if (solidMeta.ok && (solidMeta.data?.n_trees || 0) > 0) {
        try {
          const gltf = await new Promise((resolve, reject) => {
            new GLTFLoader().load(
              `${import.meta.env.BASE_URL}trees/trees_solid.glb?_v=${Date.now()}`,
              resolve,
              undefined,
              reject
            );
          });
          if (disposed) return false;
          if (treesGroup) scene.remove(treesGroup);
          treesGroup = gltf.scene;
          treesGroup.userData.n_crowns = solidMeta.data.n_trees;
          treesGroup.userData.source = "laz_solid";
          enableMeshShadows(treesGroup, { cast: true, receive: true });
          scene.add(treesGroup);
          treeCount = solidMeta.data.n_trees;
          ok = true;
        } catch {
          // fall through to points
        }
      }

      if (!ok && metaRes.ok && binRes.ok) {
        const xyz = new Float32Array(binRes.data);
        if (treesGroup) scene.remove(treesGroup);
        treesGroup = buildLazCrownPoints(metaRes.data, xyz);
        scene.add(treesGroup);
        treeCount = metaRes.data?.n_trees || treesGroup.userData.n_crowns || 0;
        ok = treeCount > 0;
      }

      const treeRes = await getWindTrees();
      if (treeRes.ok) {
        if (ladGroup) scene.remove(ladGroup);
        ladGroup = buildLadCanopyOverlay(treeRes.data);
        if (ladGroup.userData.n_points) scene.add(ladGroup);
      }
      return ok;
    }

    async function loadPackage({ keepCamera = false } = {}) {
      const [windRes, bldRes, boundRes, roadRes] = await Promise.all([
        getWindLatest(),
        getWindBuildings(),
        getWindCampusBoundary(),
        getWindRoads(),
      ]);
      if (disposed) return;
      if (!windRes.ok) {
        setStatus("error");
        setError(windRes.error || "Wind load failed");
        return;
      }

      const prevTarget = controls.target.clone();
      const prevCam = camera.position.clone();

      if (bldRes.ok) {
        const nB = bldRes.data?.n_buildings || bldRes.data?.buildings?.length || 0;
        const styleRev = (bldRes.data?.style_rev || 4) + 11; // campus slate tint
        const prevB = buildingsGroup?.userData?.n_buildings || 0;
        const prevStyle = buildingsGroup?.userData?.style_rev || 0;
        if (!buildingsGroup || nB !== prevB || styleRev !== prevStyle) {
          if (buildingsGroup) scene.remove(buildingsGroup);
          const campusRings = boundRes.ok ? boundRes.data?.rings : null;
          buildingsGroup = buildBuildings(bldRes.data, campusRings);
          buildingsGroup.userData.n_buildings = nB;
          buildingsGroup.userData.style_rev = styleRev;
          // Must stay receive:false — receive:true re-applies roof/wall stripe acne.
          enableMeshShadows(buildingsGroup, { cast: true, receive: false });
          scene.add(buildingsGroup);
        }
      }

      const lazOk = await loadLazTrees();
      if (!lazOk) {
        const treeRes = await getWindTrees();
        if (treeRes.ok) {
          const nT = treeRes.data?.n_crowns || treeRes.data?.crowns?.length || 0;
          const prevT = treesGroup?.userData?.n_crowns || 0;
          const prevSrc = treesGroup?.userData?.source || "";
          if (!treesGroup || nT !== prevT || prevSrc === "laz_points" || prevSrc === "laz_solid") {
            if (treesGroup) scene.remove(treesGroup);
            treesGroup = buildTrees(treeRes.data);
            treesGroup.userData.n_crowns = nT;
            treesGroup.userData.source = "cartoon_fallback";
            enableMeshShadows(treesGroup, { cast: true, receive: true });
            scene.add(treesGroup);
            treeCount = nT;
          }
        }
      }

      if (roadRes?.ok) {
        roadsPayloadCache = roadRes.data;
        const nR = roadRes.data?.n_segments || roadRes.data?.segments?.length || 0;
        const roadStyle = roadRes.data?.style_rev || 6;
        const prevR = roadsGroup?.userData?.n_segments || 0;
        const prevStyle = roadsGroup?.userData?.roadStyle || 0;
        if (!roadsGroup || nR !== prevR || roadStyle !== prevStyle) {
          if (roadsGroup) scene.remove(roadsGroup);
          roadsGroup = buildRoads(roadRes.data);
          roadsGroup.userData.n_segments = nR;
          roadsGroup.userData.roadStyle = roadStyle;
          scene.add(roadsGroup);
        }
        // Refresh network air-temp colours once roads are available.
        if (airTempMode.roads || airTempMode.area) rebuildAirTempLayers();
      }
      if (boundaryGroup) {
        scene.remove(boundaryGroup);
        boundaryGroup = null;
      }

      applyWindPackage(windRes.data);

      if (keepCamera) {
        controls.target.copy(prevTarget);
        camera.position.copy(prevCam);
        controls.update();
      }
    }

    async function pollForUpdate() {
      if (disposed) return;
      const st = await getWindStatus();
      if (disposed || !st.ok) return;
      const next = st.data?.updated_at || "";
      if (next && packageStamp && next !== packageStamp) {
        await loadPackage({ keepCamera: true });
      }
    }

    function tick() {
      if (disposed) return;
      const wallDt = Math.min(clock.getDelta(), 0.05);
      // Cap sim step so 3.3 m/s never races across campus in a blink.
      const simDt = Math.min(wallDt * TIME_SCALE, 0.35);
      stepParticles(simDt);
      controls.update();
      renderer.render(scene, camera);
      raf = requestAnimationFrame(tick);
    }

    loadPackage().then(() => {
      if (disposed) return;
      clock.start();
      raf = requestAnimationFrame(tick);
    });

    pollTimer = window.setInterval(pollForUpdate, POLL_MS);
    hourTimer = window.setInterval(() => {
      loadPackage({ keepCamera: true });
    }, HOUR_MS);

    return () => {
      disposed = true;
      if (window.__CFD_SHADOW__) delete window.__CFD_SHADOW__;
      solarApiRef.current = null;
      airTempApiRef.current = null;
      disposeAirTempGroups();
      cancelAnimationFrame(raf);
      window.clearInterval(pollTimer);
      window.clearInterval(hourTimer);
      ro.disconnect();
      disposeParticles();
      if (pedPlane) {
        scene.remove(pedPlane);
        pedPlane.geometry.dispose();
        pedPlane.material.map?.dispose();
        pedPlane.material.dispose();
      }
      controls.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === wrap) wrap.removeChild(renderer.domElement);
    };
  }, []);

  return (
    <div className="pointcloud-viewer wind-flow-viewer">
      <div className="pointcloud-canvas-wrap" ref={wrapRef} />
      {status === "loading" ? (
        <div className="pointcloud-loading">
          <div className="pointcloud-spinner" />
          <p>Loading CFD wind package…</p>
        </div>
      ) : null}
      {status === "error" ? (
        <div className="pointcloud-error" role="alert">
          <p>{error}</p>
        </div>
      ) : null}
      {status === "ready" && meta ? (
        <>
          <div className="wind-flow-badge">
            <strong>
              CFD Shadow · {meta.domain_label || "Hung Hom"} wind + sun shade
            </strong>
            <span>{formatStamp(meta.timestamp || meta.updated_at)}</span>
            <span>
              HKO {Number(meta.wind_from_deg ?? 0).toFixed(0)}° ·{" "}
              {Number(meta.u_ref_mps ?? 0).toFixed(1)} m/s inlet (King&apos;s Park)
            </span>
            <span>
              {hkoAirTemp
                ? `Air temp ${hkoAirTemp.temp_c.toFixed(0)}°C · ${hkoAirTemp.place} @ ~${HKO_AIR_TEMP_HEIGHT_M.toFixed(1)} m AGL (live · 30 min)`
                : "Air temp — waiting for HKO…"}
            </span>
            <span>
              {meta.wind_extent_m
                ? `${meta.wind_extent_m[0]}×${meta.wind_extent_m[1]} m domain`
                : "district domain"}
              {" · "}
              {Number(meta.n_particles || 0).toLocaleString()} tracers @ 1.5 m AGL
            </span>
            <span>
              {Number(meta.n_trees || 0)} measured crowns · LandsD solids
            </span>
            <span className="wind-flow-badge-note">
              Direct-sun shadows: SunCalc ephemeris + LAZ crowns + LandsD buildings
              (see docs/SHADOW_METHOD.md)
            </span>
          </div>
          <div className="shadow-time-panel" aria-label="Solar shadow time control">
            <div className="shadow-time-row">
              <label htmlFor="shadow-date">Date (HKT)</label>
              <input
                id="shadow-date"
                type="date"
                value={shadowDate}
                onChange={(e) => {
                  setShadowPlaying(false);
                  setShadowDate(e.target.value);
                }}
              />
              <button
                type="button"
                className="shadow-play-btn"
                onClick={() => setShadowPlaying((p) => !p)}
              >
                {shadowPlaying ? "Pause" : "Play day"}
              </button>
              <button
                type="button"
                className={`shadow-play-btn${showAirTempArea ? " is-on" : ""}`}
                onClick={() => setShowAirTempArea((v) => !v)}
                title="HKO AWS IDW air-temp layer over the domain (~1.2 m AGL)"
              >
                {showAirTempArea ? "Hide area temp" : "Area temp"}
              </button>
            </div>
            <div className="shadow-time-row">
              <label htmlFor="shadow-minutes">{formatHm(shadowMinutes)}</label>
              <input
                id="shadow-minutes"
                type="range"
                min={0}
                max={24 * 60 - 1}
                step={1}
                value={shadowMinutes}
                onChange={(e) => {
                  setShadowPlaying(false);
                  setShadowMinutes(Number(e.target.value));
                }}
              />
            </div>
            <p className="shadow-time-meta">
              Daylight ~{formatHm(dayBounds.sunriseMin ?? 0)}–
              {formatHm(dayBounds.sunsetMin ?? 0)} HKT
              {" · "}
              {solarInfo.aboveHorizon
                ? `Sun alt ${solarInfo.altitudeDeg.toFixed(1)}° · az from S ${solarInfo.azimuthDeg.toFixed(0)}°`
                : "Night — drag slider into daylight for shadows"}
            </p>
          </div>
          <div className="wind-flow-legend" aria-label="Wind speed colour scale">
            <div className="wind-flow-legend-bar" />
            <div className="wind-flow-legend-labels">
              <span>0</span>
              <span>wind speed (m/s)</span>
              <span>{Number(meta.vmax_mps || 0).toFixed(1)}</span>
            </div>
            <p className="wind-flow-legend-hint">
              1.5 m AGL · Hung Hom district trails · scrub time for shade
            </p>
            {showAirTempRoads || showAirTempArea ? (
              <>
                <div className="air-temp-legend-bar" aria-hidden="true" />
                <div className="wind-flow-legend-labels">
                  <span>{AIR_TEMP_COLOR_MIN_C}°C</span>
                  <span>
                    {showAirTempRoads && showAirTempArea
                      ? "air temp roads + area"
                      : showAirTempRoads
                        ? "road / path air temp"
                        : "area air temp"}{" "}
                    (HKO IDW)
                  </span>
                  <span>{AIR_TEMP_COLOR_MAX_C}°C</span>
                </div>
                <p className="wind-flow-legend-hint">
                  Screen height ~{HKO_AIR_TEMP_HEIGHT_M.toFixed(1)} m AGL ·{" "}
                  {airTempLayerMeta?.nStations || 0} nearby AWS
                  {airTempLayerMeta
                    ? ` · stations ${Number(airTempLayerMeta.tMin).toFixed(0)}–${Number(airTempLayerMeta.tMax).toFixed(0)}°C`
                    : ""}{" "}
                  · network-first · not CFD thermal
                </p>
              </>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}
