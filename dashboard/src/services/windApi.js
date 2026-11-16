/** Static packages under /public (no backend required). */

/** Vite base (`/` locally, `/cfd-shadow/` on GitHub Pages). */
const BASE = import.meta.env.BASE_URL || "/";

function assetUrl(path) {
  const clean = String(path || "").replace(/^\/+/, "");
  return `${BASE}${clean}`;
}

async function fetchJson(path, timeoutMs = 60000) {
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(assetUrl(path), { signal: ctrl.signal, cache: "no-store" });
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
  return fetchJson("wind/wind_latest.json", 60000);
}

export async function getWindStatus() {
  const res = await fetchJson("wind/wind_latest.json", 15000);
  if (!res.ok) return res;
  return {
    ok: true,
    data: { updated_at: res.data?.updated_at || "" },
  };
}

/** Prefer LandsD 1.5 km context; fall back to CFD wind package buildings. */
export async function getWindBuildings() {
  const ctx = await fetchJson(`buildings/context_1p5km.json?_v=${Date.now()}`, 60000);
  if (ctx.ok && (ctx.data?.buildings?.length || 0) > 0) return ctx;
  return fetchJson(`wind/buildings.json?_v=${Date.now()}`, 30000);
}

/** Cartoon crowns from wind package — used only as fallback. */
export async function getWindTrees() {
  return fetchJson(`wind/trees.json?_v=${Date.now()}`, 60000);
}

/** LAZ crown meta (points live in crowns.bin). */
export async function getLazCrownsMeta() {
  return fetchJson(`trees/crowns.meta.json?_v=${Date.now()}`, 30000);
}

export async function getLazCrownsBin() {
  try {
    const res = await fetch(assetUrl(`trees/crowns.bin?_v=${Date.now()}`), {
      cache: "no-store",
    });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return { ok: true, data: await res.arrayBuffer() };
  } catch (error) {
    return { ok: false, error: error?.message || "crowns.bin failed" };
  }
}

export async function getSolidTreesMeta() {
  return fetchJson(`trees/trees_solid.meta.json?_v=${Date.now()}`, 15000);
}

/** Prefer 1.5 km OSM+pedestrian roads; fall back to wind package. */
export async function getWindRoads() {
  const ctx = await fetchJson(`buildings/roads_1p5km.json?_v=${Date.now()}`, 60000);
  if (ctx.ok && (ctx.data?.segments?.length || 0) > 0) return ctx;
  return fetchJson(`wind/roads.json?_v=${Date.now()}`, 30000);
}

export async function getWindCampusBoundary() {
  return fetchJson("wind/campus_boundary.json", 30000);
}

/** Live HKO regional air temperature (CORS-open rhrread). Prefer King's Park. */
const HKO_RHRREAD =
  "https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=rhrread&lang=en";

/**
 * Approximate HK1980 (EPSG:2326) easting/northing for HKO temperature AWS.
 * Air temperature is measured in a Stevenson screen ≈ 1.2 m AGL (HKO standard).
 */
export const HKO_TEMP_STATIONS_HK80 = {
  "King's Park": [835848.2, 819213.5],
  "Hong Kong Observatory": [835989.3, 818141.6],
  "Hong Kong Park": [834704.1, 815404.3],
  "Kowloon City": [837723.2, 821217.8],
  "Kai Tak Runway Park": [840021.2, 818881.7],
  "Happy Valley": [836961.2, 814662.3],
  "Sham Shui Po": [834478.1, 821240.0],
  "Wong Tai Sin": [838135.2, 822546.7],
  "Kwun Tong": [841329.7, 819225.4],
  "Sha Tin": [839678.9, 829191.1],
  "Tseung Kwan O": [845657.1, 819227.4],
  "Wong Chuk Hang": [835868.6, 812137.6],
  "Stanley": [840095.8, 808816.0],
  "Tsing Yi": [829070.1, 822769.7],
  "Chek Lap Kok": [809903.4, 818914.7],
  "Tai Po": [837200.0, 834200.0],
  "Sai Kung": [847200.0, 825000.0],
  "Tuen Mun": [815500.0, 827000.0],
  "Lau Fau Shan": [810500.0, 832500.0],
  "Ta Kwu Ling": [837000.0, 842000.0],
  "Shek Kong": [825000.0, 832000.0],
  "Tsuen Wan Shing Mun Valley": [826500.0, 824500.0],
  "Tsuen Wan Ho Koon": [824500.0, 825500.0],
  "Shau Kei Wan": [842500.0, 816500.0],
  "Yuen Long Park": [820500.0, 834000.0],
  "Tai Mei Tuk": [843000.0, 834500.0],
};

/** HKO screen / shed air-temperature height (official ≈ 1.2 m AGL). */
export const HKO_AIR_TEMP_HEIGHT_M = 1.2;

export async function getHkoAirTemp(preferredPlace = "King's Park") {
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 20000);
  try {
    const res = await fetch(HKO_RHRREAD, { signal: ctrl.signal, cache: "no-store" });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const data = await res.json();
    const rows = Array.isArray(data?.temperature?.data) ? data.temperature.data : [];
    const stations = [];
    for (const r of rows) {
      const place = String(r?.place || "").trim();
      const temp_c = Number(r?.value);
      if (!place || Number.isNaN(temp_c)) continue;
      const hk80 = HKO_TEMP_STATIONS_HK80[place] || null;
      stations.push({
        place,
        temp_c,
        unit: String(r?.unit || "C"),
        easting: hk80 ? hk80[0] : null,
        northing: hk80 ? hk80[1] : null,
      });
    }
    const pick =
      stations.find((r) => r.place === preferredPlace) ||
      stations.find((r) => /king'?s?\s*park/i.test(r.place)) ||
      stations[0];
    if (!pick) throw new Error("No HKO air temperature in response");
    return {
      ok: true,
      data: {
        place: pick.place,
        temp_c: pick.temp_c,
        unit: pick.unit,
        height_m_agl: HKO_AIR_TEMP_HEIGHT_M,
        record_time: data?.temperature?.recordTime || data?.updateTime || "",
        update_time: data?.updateTime || "",
        stations,
      },
    };
  } catch (error) {
    return { ok: false, error: error?.message || "HKO air temp failed" };
  } finally {
    window.clearTimeout(timer);
  }
}
