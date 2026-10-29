"""Hourly HKO King's Park remap for CFD_Shadow wind_latest.json.

Fetches https://data.weather.gov.hk/.../latest_10min_wind.csv, then
rotates/scales the coarse UVW grid (no OpenFOAM re-solve).

Usage:
  python scripts/hourly_wind_update.py
  python scripts/hourly_wind_update.py --wind dashboard/public/wind/wind_latest.json
"""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LATEST_10MIN_WIND = (
    "https://data.weather.gov.hk/weatherAPI/hko_data/regional-weather/latest_10min_wind.csv"
)

COMPASS_TO_DEG = {
    "N": 0.0,
    "NNE": 22.5,
    "NE": 45.0,
    "ENE": 67.5,
    "E": 90.0,
    "ESE": 112.5,
    "SE": 135.0,
    "SSE": 157.5,
    "S": 180.0,
    "SSW": 202.5,
    "SW": 225.0,
    "WSW": 247.5,
    "W": 270.0,
    "WNW": 292.5,
    "NW": 315.0,
    "NNW": 337.5,
}
FULL_NAME_TO_COMPASS = {
    "NORTH": "N",
    "NORTHEAST": "NE",
    "EAST": "E",
    "SOUTHEAST": "SE",
    "SOUTH": "S",
    "SOUTHWEST": "SW",
    "WEST": "W",
    "NORTHWEST": "NW",
}

DEFAULT_WIND_PATHS = [
    ROOT / "dashboard" / "public" / "wind" / "wind_latest.json",
    ROOT / "data" / "wind" / "wind_latest.json",
]


def compass_to_deg(token: str) -> float | None:
    key = token.strip().upper()
    if key in {"", "N/A", "CALM", "VARIABLE", "VRB"}:
        return None
    if key in COMPASS_TO_DEG:
        return COMPASS_TO_DEG[key]
    compact = key.replace("-", "").replace(" ", "")
    if compact in FULL_NAME_TO_COMPASS:
        return COMPASS_TO_DEG[FULL_NAME_TO_COMPASS[compact]]
    try:
        return float(key)
    except ValueError:
        return None


def parse_stamp(raw: str) -> datetime | None:
    text = (raw or "").strip()
    for fmt in ("%Y%m%d%H%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text[:16] if "T" in text or " " in text else text[:12], fmt)
        except ValueError:
            continue
    # HKO often: yyyyMMddHHmm
    try:
        return datetime.strptime(text[:12], "%Y%m%d%H%M")
    except ValueError:
        return None


def _b64_f16(arr: np.ndarray) -> str:
    return base64.b64encode(np.asarray(arr, dtype="<f2").tobytes()).decode("ascii")


def _decode_f16(b64: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(b64), dtype="<f2").astype(np.float32).copy()


def fetch_latest_kp() -> dict:
    req = Request(LATEST_10MIN_WIND, headers={"User-Agent": "cfd-shadow-hourly-wind"})
    with urlopen(req, timeout=45) as resp:
        text = resp.read().decode("utf-8-sig")
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 4 or "king" not in row[1].lower():
            continue
        obs = parse_stamp(row[0])
        deg = compass_to_deg(row[2])
        try:
            kmh = float(row[3])
        except ValueError as exc:
            raise RuntimeError("King's Park speed missing in latest feed") from exc
        if obs is None or deg is None:
            raise RuntimeError("King's Park calm/missing in latest feed")
        return {
            "station": "King's Park",
            "timestamp": obs.strftime("%Y-%m-%dT%H:%M+08:00"),
            "u_ref_mps": round(kmh / 3.6, 4),
            "wind_from_deg": float(deg),
            "z_ref_m": 25.0,
            "source": LATEST_10MIN_WIND,
        }
    raise RuntimeError("King's Park row not found in latest_10min_wind.csv")


def remap_uvw(
    u: np.ndarray,
    v: np.ndarray,
    w: np.ndarray,
    *,
    old_from_deg: float,
    new_from_deg: float,
    old_u_ref: float,
    new_u_ref: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    dtheta = math.radians(new_from_deg - old_from_deg)
    c = math.cos(dtheta)
    s = math.sin(dtheta)
    u2 = u * c + v * s
    v2 = -u * s + v * c
    scale = (new_u_ref / old_u_ref) if old_u_ref > 1e-6 else 1.0
    scale = float(np.clip(scale, 0.15, 4.0))
    return u2 * scale, v2 * scale, w * scale


def update_package(path: Path, slot: dict, *, dry: bool) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    inlet = data.get("inlet") or {}
    old_from = float(inlet.get("wind_from_deg", 90.0))
    old_uref = float(inlet.get("u_ref_mps", 3.0))
    new_from = float(slot["wind_from_deg"])
    new_uref = float(slot["u_ref_mps"])

    nx = int(data["domain"]["nx"])
    ny = int(data["domain"]["ny"])
    nz = int(data["domain"]["nz"])
    n = nx * ny * nz

    u = _decode_f16(data["grid"]["u"])
    v = _decode_f16(data["grid"]["v"])
    w = _decode_f16(data["grid"]["w"])
    if u.size != n:
        raise RuntimeError(f"{path}: UVW size {u.size} != domain {n}")

    u2, v2, w2 = remap_uvw(
        u,
        v,
        w,
        old_from_deg=old_from,
        new_from_deg=new_from,
        old_u_ref=old_uref,
        new_u_ref=new_uref,
    )

    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    data["note"] = (
        "Hourly HKO remap of campus UVW (rotate+scale). "
        "Replace with full CFD export when a new simpleFoam case is ready."
    )
    data["inlet"] = {
        "u_ref_mps": new_uref,
        "wind_from_deg": new_from,
        "z_ref_m": float(slot.get("z_ref_m", inlet.get("z_ref_m", 25))),
        "timestamp": slot["timestamp"],
        "station": slot.get("station", "King's Park"),
        "source": slot.get("source"),
        "remap_from": {"u_ref_mps": old_uref, "wind_from_deg": old_from},
    }
    data["grid"]["u"] = _b64_f16(u2.reshape(nx, ny, nz))
    data["grid"]["v"] = _b64_f16(v2.reshape(nx, ny, nz))
    data["grid"]["w"] = _b64_f16(w2.reshape(nx, ny, nz))

    print(
        f"{'[dry] ' if dry else ''}"
        f"{path.name}: {old_from:.0f} deg/{old_uref:.2f} m/s -> "
        f"{new_from:.0f} deg/{new_uref:.2f} m/s  ({slot['timestamp']})"
    )
    if not dry:
        path.write_text(json.dumps(data), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wind", type=Path, action="append", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    paths = args.wind or DEFAULT_WIND_PATHS
    slot = fetch_latest_kp()
    print(
        f"HKO King's Park latest: {slot['timestamp']}  "
        f"from {slot['wind_from_deg']:.0f} deg  {slot['u_ref_mps']:.2f} m/s"
    )

    ok = 0
    for path in paths:
        path = path if path.is_absolute() else (ROOT / path)
        if not path.exists():
            print(f"skip missing: {path}", file=sys.stderr)
            continue
        update_package(path, slot, dry=args.dry_run)
        ok += 1
    if ok == 0:
        print("No wind_latest.json updated.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
