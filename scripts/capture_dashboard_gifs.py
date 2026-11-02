"""Capture proper 3D dashboard GIFs for the ITF PPT.

1) dashboard_shadow_day_orbit.gif
   - Scrub sunrise → sunset (full daylight shadow motion)
   - Orbit the camera so the 3D relief of moving shadows is clear
   - Hide wind tracers so shade is readable

2) dashboard_wind_orbit.gif
   - Pedestrian wind tracers at 1.5 m AGL
   - Orbit the camera (not a single fixed side / top)

Requires Vite on http://127.0.0.1:5175/ and Playwright Chromium.
"""

from __future__ import annotations

import base64
import io
import math
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(r"D:\CFD_Shadow")
OUT_DIR = ROOT / "outputs" / "gifs"
URL = "http://127.0.0.1:5175/"
VIEWPORT = {"width": 1400, "height": 860}
OUT_WIDTH = 1000

# Representative summer day — long, readable shadow arcs for ITF.
SHADOW_DATE = "2026-07-15"
SHADOW_FRAMES = 48
# Wind: slow camera + long dwell so tracer advection reads clearly.
WIND_FRAMES = 56
WIND_HOLD_FRAMES = 14  # camera fixed first — pure particle motion
WIND_DWELL_MS = 380  # wall time between snaps (particles keep integrating)
WIND_GIF_MS = 170  # slower playback in PPT/slideshow
FRAME_PAUSE_MS = 70


def ensure_playwright():
    try:
        from playwright.sync_api import sync_playwright

        return sync_playwright
    except ImportError:
        import subprocess

        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright", "-q"])
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
        from playwright.sync_api import sync_playwright

        return sync_playwright


def wait_ready(page):
    # Avoid networkidle — hourly poll / HMR keep the network busy.
    page.goto(URL, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_function(
        "() => window.__CFD_SHADOW__ && window.__CFD_SHADOW__.ready === true"
        " && typeof window.__CFD_SHADOW__.setOrbitView === 'function'"
        " && typeof window.__CFD_SHADOW__.setSolarTime === 'function'",
        timeout=180_000,
    )
    page.wait_for_timeout(2800)


def snap(page, quality: float = 0.80) -> Image.Image:
    data_url = page.evaluate(f"() => window.__CFD_SHADOW__.snapshotDataUrl({quality})")
    if not data_url or not data_url.startswith("data:image"):
        raise RuntimeError("bad snapshot")
    b64 = data_url.split(",", 1)[1]
    img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    h = int(img.height * (OUT_WIDTH / img.width))
    return img.resize((OUT_WIDTH, h), Image.Resampling.LANCZOS)


def save_gif(frames: list[Image.Image], path: Path, duration_ms: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(f"Wrote {path} ({path.stat().st_size / 1e6:.2f} MB, {len(frames)} frames)")


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def capture_shadow_day(page) -> list[Image.Image]:
    """Full-day shade with a gentle 3D camera orbit."""
    page.evaluate(
        """([date]) => {
          window.__CFD_SHADOW__.setWindVisible(false);
          window.__CFD_SHADOW__.setAutoRotate(false);
          const b = window.__CFD_SHADOW__.getDayBounds(date);
          window.__CFD_SHADOW__._bounds = b;
          // Start just after sunrise so long shadows read clearly.
          window.__CFD_SHADOW__.setSolarTime(date, b.sunriseMin + 8);
          window.__CFD_SHADOW__.setOrbitView(-35, 34, 1.02);
          return b;
        }""",
        [SHADOW_DATE],
    )
    page.wait_for_timeout(500)
    bounds = page.evaluate("() => window.__CFD_SHADOW__._bounds")
    start = int(bounds["sunriseMin"]) + 8
    end = int(bounds["sunsetMin"]) - 8
    if end <= start:
        start, end = 6 * 60 + 20, 18 * 60 - 20

    frames: list[Image.Image] = []
    n = SHADOW_FRAMES
    for i in range(n):
        t = i / (n - 1)
        minutes = int(round(lerp(start, end, t)))
        # Orbit ~200° so buildings/trees read in 3D while shadows sweep.
        az = lerp(-40, 160, t)
        # Elevate slightly at midday (shorter shadows), lower near dawn/dusk.
        elev = lerp(28, 40, math.sin(t * math.pi))
        dist = lerp(1.05, 0.92, math.sin(t * math.pi))
        page.evaluate(
            """([date, minutes, az, elev, dist]) => {
              window.__CFD_SHADOW__.setSolarTime(date, minutes);
              window.__CFD_SHADOW__.setOrbitView(az, elev, dist);
            }""",
            [SHADOW_DATE, minutes, az, elev, dist],
        )
        page.wait_for_timeout(FRAME_PAUSE_MS)
        frames.append(snap(page, 0.82))
        if (i + 1) % 8 == 0:
            hh, mm = divmod(minutes, 60)
            print(f"  shadow {i + 1}/{n}  {hh:02d}:{mm:02d} HKT  az={az:.0f}°")
    return frames


def capture_wind_orbit(page) -> list[Image.Image]:
    """Slow 3D wind GIF: particle motion first, then a gentle multi-side orbit.

    Camera steps are small (~2°/frame) so tracer advection stays readable.
    """
    start_az, end_az = -25.0, 95.0  # ~120° sweep — enough to read 3D, not a blur
    start_elev, end_elev = 30.0, 36.0
    start_dist, end_dist = 0.98, 0.90

    page.evaluate(
        """([date, az, elev, dist]) => {
          window.__CFD_SHADOW__.setWindVisible(true);
          window.__CFD_SHADOW__.setAutoRotate(false);
          window.__CFD_SHADOW__.setSolarTime(date, 10 * 60 + 30);
          window.__CFD_SHADOW__.setOrbitView(az, elev, dist);
        }""",
        [SHADOW_DATE, start_az, start_elev, start_dist],
    )
    # Warm-up so trails form before the first frame.
    page.wait_for_timeout(1200)

    frames: list[Image.Image] = []

    # 1) Hold camera — wind motion only.
    for i in range(WIND_HOLD_FRAMES):
        page.wait_for_timeout(WIND_DWELL_MS)
        frames.append(snap(page, 0.78))
        if (i + 1) % 7 == 0:
            print(f"  wind hold {i + 1}/{WIND_HOLD_FRAMES}  (camera fixed)")

    # 2) Slow orbit while particles keep integrating.
    n_orbit = WIND_FRAMES
    for i in range(n_orbit):
        t = i / (n_orbit - 1)
        # Ease-in/out so early/late frames linger on flow.
        te = t * t * (3 - 2 * t)
        az = lerp(start_az, end_az, te)
        elev = lerp(start_elev, end_elev, math.sin(te * math.pi))
        dist = lerp(start_dist, end_dist, te)
        page.evaluate(
            """([az, elev, dist]) => {
              window.__CFD_SHADOW__.setOrbitView(az, elev, dist);
            }""",
            [az, elev, dist],
        )
        page.wait_for_timeout(WIND_DWELL_MS)
        frames.append(snap(page, 0.78))
        if (i + 1) % 8 == 0:
            print(f"  wind orbit {i + 1}/{n_orbit}  az={az:.0f}° elev={elev:.0f}°")
    return frames


def main() -> int:
    mode = "both"
    if len(sys.argv) > 1:
        mode = sys.argv[1].strip().lower()  # shadow | wind | both

    sync_playwright = ensure_playwright()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    shadow_frames: list[Image.Image] = []
    wind_frames: list[Image.Image] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
        print("Loading dashboard…")
        wait_ready(page)

        if mode in ("shadow", "both", "all"):
            print("Capturing full-day shadow orbit GIF…")
            shadow_frames = capture_shadow_day(page)
            save_gif(shadow_frames, OUT_DIR / "dashboard_shadow_day_orbit.gif", duration_ms=110)

        if mode in ("wind", "both", "all"):
            print("Capturing slow orbiting wind GIF…")
            wind_frames = capture_wind_orbit(page)
            save_gif(wind_frames, OUT_DIR / "dashboard_wind_orbit.gif", duration_ms=WIND_GIF_MS)

        browser.close()

    if mode in ("shadow", "both", "all") and len(shadow_frames) < 12:
        print("Shadow capture produced too few frames", file=sys.stderr)
        return 1
    if mode in ("wind", "both", "all") and len(wind_frames) < 12:
        print("Wind capture produced too few frames", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
