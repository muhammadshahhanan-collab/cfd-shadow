/** Static packages under /public (no backend required). */

async function fetchJson(url, timeoutMs = 60000) {
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: ctrl.signal, cache: "no-store" });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return { ok: true, data: await res.json() };
  } catch (error) {
    return {
      ok: false,
      error: error?.message || "Request failed",
    };
  } finally {
    window.clearTimeout(timer);
  }
}

export async function getWindLatest() {
  return fetchJson("/wind/wind_latest.json", 60000);
}

export async function getWindStatus() {
  const res = await fetchJson("/wind/wind_latest.json", 15000);
  if (!res.ok) return res;
  return {
    ok: true,
    data: { updated_at: res.data?.updated_at || "" },
  };
}

/** Prefer LandsD 1.5 km context; fall back to CFD wind package buildings. */
export async function getWindBuildings() {
  const ctx = await fetchJson(`/buildings/context_1p5km.json?_v=${Date.now()}`, 60000);
  if (ctx.ok && (ctx.data?.buildings?.length || 0) > 0) return ctx;
  return fetchJson(`/wind/buildings.json?_v=${Date.now()}`, 30000);
}

/** Cartoon crowns from wind package — used only as fallback. */
export async function getWindTrees() {
  return fetchJson(`/wind/trees.json?_v=${Date.now()}`, 60000);
}

/** LAZ crown meta (points live in crowns.bin). */
export async function getLazCrownsMeta() {
  return fetchJson(`/trees/crowns.meta.json?_v=${Date.now()}`, 30000);
}

export async function getLazCrownsBin() {
  try {
    const res = await fetch(`/trees/crowns.bin?_v=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return { ok: true, data: await res.arrayBuffer() };
  } catch (error) {
    return { ok: false, error: error?.message || "crowns.bin failed" };
  }
}

export async function getSolidTreesMeta() {
  return fetchJson(`/trees/trees_solid.meta.json?_v=${Date.now()}`, 15000);
}

/** Prefer 1.5 km OSM+pedestrian roads; fall back to wind package. */
export async function getWindRoads() {
  const ctx = await fetchJson(`/buildings/roads_1p5km.json?_v=${Date.now()}`, 60000);
  if (ctx.ok && (ctx.data?.segments?.length || 0) > 0) return ctx;
  return fetchJson(`/wind/roads.json?_v=${Date.now()}`, 30000);
}

export async function getWindCampusBoundary() {
  return fetchJson("/wind/campus_boundary.json", 30000);
}
