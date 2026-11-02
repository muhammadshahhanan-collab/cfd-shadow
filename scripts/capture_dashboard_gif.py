"""Capture an animated GIF of the live CFD_Shadow dashboard plan view.

Requires the Vite app on http://127.0.0.1:5175/ and Playwright Chromium.
"""

from __future__ import annotations

import base64
import io
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(r"D:\CFD_Shadow")
OUT_DIR = ROOT / "outputs" / "gifs"
OUT_GIF = OUT_DIR / "dashboard_wind_plan_view.gif"
URL = "http://127.0.0.1:5175/"
N_FRAMES = 28
FRAME_MS = 110
VIEWPORT = {"width": 1280, "height": 800}
OUT_WIDTH = 960


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Installing playwright…")
        import subprocess

        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright", "-q"])
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
        from playwright.sync_api import sync_playwright

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frames: list[Image.Image] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
        page.goto(URL, wait_until="networkidle", timeout=120_000)
        page.wait_for_function(
            "() => window.__CFD_SHADOW__ && window.__CFD_SHADOW__.ready === true",
            timeout=180_000,
        )
        # Settle meshes / first particle steps
        page.wait_for_timeout(2500)
        ok = page.evaluate("() => window.__CFD_SHADOW__.setPlanView()")
        if not ok:
            print("setPlanView failed", file=sys.stderr)
            browser.close()
            return 1
        page.wait_for_timeout(400)

        for i in range(N_FRAMES):
            data_url = page.evaluate("() => window.__CFD_SHADOW__.snapshotDataUrl(0.78)")
            if not data_url or not data_url.startswith("data:image"):
                print(f"frame {i}: bad snapshot", file=sys.stderr)
                continue
            b64 = data_url.split(",", 1)[1]
            img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
            h = int(img.height * (OUT_WIDTH / img.width))
            frames.append(img.resize((OUT_WIDTH, h), Image.Resampling.LANCZOS))
            page.wait_for_timeout(FRAME_MS)
            if (i + 1) % 7 == 0:
                print(f"  captured {i + 1}/{N_FRAMES}")

        browser.close()

    if len(frames) < 8:
        print(f"Too few frames ({len(frames)})", file=sys.stderr)
        return 1

    # Adaptive palette keeps PPT/email size manageable while preserving wind colour.
    frames[0].save(
        OUT_GIF,
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_MS,
        loop=0,
        optimize=True,
        disposal=2,
    )
    mb = OUT_GIF.stat().st_size / 1e6
    print(f"Wrote {OUT_GIF} ({mb:.2f} MB, {len(frames)} frames)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
