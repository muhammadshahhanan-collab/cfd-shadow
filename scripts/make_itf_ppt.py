"""ITF PPT: wind ventilation + building/tree shade — scientific brief.

Style: white deck, green titles, rounded cards, skyline footer.
Visuals: final wind map GIFs, LAZ crown side elevation, live dashboard screenshots.
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(r"d:\CFD_Shadow")
CFD = Path(r"d:\CFD")
OUT = ROOT / "outputs" / "ITF_Wind_Shade_Brief.pptx"
# Fallback if the primary file is open/locked in PowerPoint.
OUT_ALT = ROOT / "outputs" / "ITF_Wind_Shade_Brief_v2.pptx"
ASSETS = Path(
    r"C:\Users\mshanan\.cursor\projects\d-CFD-Shadow\assets"
)

# Orbiting 3D dashboard GIFs (primary) + map GIF fallbacks
IMG_WIND_DASH = ROOT / "outputs" / "gifs" / "dashboard_wind_orbit.gif"
IMG_SHADOW_DAY = ROOT / "outputs" / "gifs" / "dashboard_shadow_day_orbit.gif"
IMG_WIND_PLAN = ROOT / "outputs" / "gifs" / "dashboard_wind_plan_view.gif"
IMG_WIND_MAP = CFD / "outputs" / "animations" / "polyU_campus_DSM_wind_20260714_day.gif"
IMG_WIND_MAP_FALLBACK = (
    CFD / "outputs" / "animations" / "polyU_campus_DSM_wind_20260714_day.first_frame.png"
)
IMG_WIND_PARTICLES = CFD / "outputs" / "animations" / "polyU_campus_particles_20260811.gif"
IMG_WIND_PARTICLES_FALLBACK = (
    CFD / "outputs" / "animations" / "polyU_campus_particles_20260811.first_frame.png"
)
IMG_WIND_3D = CFD / "outputs" / "share" / "polyU_campus_DSM_3D_day_soft.gif"
IMG_WIND_3D_FALLBACK = CFD / "outputs" / "share" / "polyU_campus_DSM_3D_day_soft_frame.png"

# Tree structure — side elevation (not top-down)
IMG_TREES_SIDE = ROOT / "outputs" / "ppt_media" / "trees_side_elevation.png"

# Updated live dashboard screenshots
IMG_DASH_TOP = (
    ASSETS
    / "c__Users_mshanan_AppData_Roaming_Cursor_User_workspaceStorage_354411cee1a75e7fed059c64dd0d7b9f_images_image-aa715212-4340-4882-824a-1a4d577bbdb8.png"
)
IMG_DASH_STREET = (
    ASSETS
    / "c__Users_mshanan_AppData_Roaming_Cursor_User_workspaceStorage_354411cee1a75e7fed059c64dd0d7b9f_images_image-43e87e80-5150-4a26-b26c-b438dc0dce84.png"
)

GREEN = RGBColor(0x2E, 0xA8, 0x4A)
GREEN_DK = RGBColor(0x1F, 0x7A, 0x38)
TEAL = RGBColor(0x1A, 0x8A, 0x8C)
BLUE = RGBColor(0x2F, 0x6F, 0xB8)
ORANGE = RGBColor(0xD9, 0x7A, 0x2B)
PURPLE = RGBColor(0x7A, 0x4F, 0xB0)
DARK = RGBColor(0x2A, 0x2A, 0x2A)
MUTED = RGBColor(0x5A, 0x5A, 0x5A)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
CARD_BG = RGBColor(0xF7, 0xF9, 0xFB)
GOLD = RGBColor(0xC9, 0xA2, 0x4A)
GOLD_BG = RGBColor(0xFF, 0xF8, 0xE7)
SKYLINE = RGBColor(0xD8, 0xE0, 0xE8)
LINE = RGBColor(0xE2, 0xE8, 0xEE)


def font(run, size: int, bold: bool = False, color=DARK):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = "Calibri"


def set_run_text(p, text: str, size: int, bold: bool = False, color=DARK):
    p.clear()
    run = p.add_run()
    run.text = text
    font(run, size, bold, color)


def add_para(tf, text: str, size: int, bold: bool = False, color=DARK, space_after: int = 6):
    if tf.paragraphs[0].text == "" and len(tf.paragraphs) == 1 and not tf.paragraphs[0].runs:
        p = tf.paragraphs[0]
    else:
        p = tf.add_paragraph()
    set_run_text(p, text, size, bold, color)
    p.space_after = Pt(space_after)
    p.level = 0
    return p


def blank_slide(prs: Presentation):
    return prs.slides.add_slide(prs.slide_layouts[6])


def round_rect(slide, left, top, width, height, fill=CARD_BG, line=LINE, line_pt: float = 1.0):
    shp = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height)
    )
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(line_pt)
    try:
        shp.adjustments[0] = 0.08
    except Exception:
        pass
    return shp


def skyline_footer(slide, prs: Presentation):
    base_y = prs.slide_height - Inches(0.42)
    strip = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), base_y - Inches(0.02), prs.slide_width, Inches(0.44)
    )
    strip.fill.solid()
    strip.fill.fore_color.rgb = RGBColor(0xF2, 0xF5, 0xF8)
    strip.line.fill.background()
    x = Inches(0.3)
    heights = [0.18, 0.28, 0.22, 0.35, 0.16, 0.30, 0.24, 0.38, 0.20, 0.26, 0.32, 0.18, 0.29]
    for h in heights * 3:
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, x, base_y + Inches(0.40) - Inches(h), Inches(0.16), Inches(h)
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = SKYLINE
        bar.line.fill.background()
        x += Inches(0.20)
        if x > prs.slide_width - Inches(0.2):
            break


def title_green(slide, text: str, left=0.55, top=0.28, width=12.2):
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(0.55))
    set_run_text(box.text_frame.paragraphs[0], text, 30, True, GREEN)
    return box


def subtitle(slide, text: str, left=0.55, top=0.78, width=12.2):
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(0.35))
    set_run_text(box.text_frame.paragraphs[0], text, 14, False, MUTED)
    return box


def body_box(slide, left, top, width, height):
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    box.text_frame.word_wrap = True
    return box.text_frame


def pick_img(*paths: Path) -> Path | None:
    for p in paths:
        if p is not None and p.exists():
            return p
    return None


def try_picture(slide, path: Path | None, left, top, width, height, placeholder="Figure"):
    if path is not None and path.exists():
        slide.shapes.add_picture(str(path), Inches(left), Inches(top), Inches(width), Inches(height))
        return True
    ph = round_rect(slide, left, top, width, height, GOLD_BG, GOLD, 1.5)
    tf = ph.text_frame
    tf.word_wrap = True
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    set_run_text(tf.paragraphs[0], placeholder, 13, False, MUTED)
    return False


def slide_use_case_wind(prs):
    s = blank_slide(prs)
    skyline_footer(s, prs)
    title_green(s, "Application — Pedestrian Wind Ventilation")
    subtitle(s, "Campus-scale CFD wind field at ~1.5 m AGL · hourly HKO King's Park inlet")

    round_rect(s, 0.40, 1.20, 7.55, 5.25, GOLD_BG, GOLD, 1.5)
    cap = body_box(s, 0.55, 1.30, 7.25, 0.30)
    set_run_text(cap.paragraphs[0], "3D orbit — 1.5 m AGL tracers · campus digital twin", 13, True, GREEN_DK)
    wind = pick_img(IMG_WIND_DASH, IMG_WIND_PLAN, IMG_WIND_MAP, IMG_WIND_MAP_FALLBACK)
    try_picture(s, wind, 0.55, 1.65, 7.25, 4.05, "Dashboard wind orbit GIF")
    note = body_box(s, 0.55, 5.80, 7.25, 0.45)
    add_para(note, "Colour = speed (m/s) · orbiting camera · LAZ crowns · LandsD buildings", 11, False, MUTED, 0)

    tf = body_box(s, 8.20, 1.25, 4.70, 5.2)
    add_para(tf, "Objectives", 16, True, DARK, 8)
    for it in [
        "Identify sheltered walking routes and seating under typical afternoon wind.",
        "Flag channelled acceleration between tall blocks.",
        "Quantify canopy drag effects on pedestrian-level speed.",
        "Cover PolyU core and Block Z north pad.",
        "Couple to hourly King's Park wind (HKO) without a full re-solve.",
        "Support outdoor-event and wayfinding planning.",
    ]:
        add_para(tf, f"•  {it}", 13, False, DARK, 7)


def slide_use_case_shade(prs):
    s = blank_slide(prs)
    skyline_footer(s, prs)
    title_green(s, "Application — Building & Tree Shade")
    subtitle(s, "Direct-beam solar occlusion · measured LiDAR crowns · time-resolved HKT sun path")

    round_rect(s, 0.40, 1.20, 7.55, 5.25, GOLD_BG, GOLD, 1.5)
    cap = body_box(s, 0.55, 1.30, 7.25, 0.30)
    set_run_text(cap.paragraphs[0], "3D full-day shade — sunrise→sunset · orbiting camera", 13, True, GREEN_DK)
    shade = pick_img(IMG_SHADOW_DAY, IMG_TREES_SIDE)
    try_picture(s, shade, 0.55, 1.65, 7.25, 4.05, "Dashboard shade day GIF")
    note = body_box(s, 0.55, 5.80, 7.25, 0.45)
    add_para(note, "Direct-beam occlusion · LandsD buildings + LAZ crowns · HKT sun path (15 Jul 2026)", 11, False, MUTED, 0)

    tf = body_box(s, 8.20, 1.25, 4.70, 5.2)
    add_para(tf, "Objectives", 16, True, DARK, 8)
    for it in [
        "Locate outdoor areas shaded by buildings and/or real tree crowns.",
        "Assess summer afternoon usability for heat-sensitive users.",
        "Scrub any HKT date/time; sun direction updates shadows.",
        "Use measured LiDAR geometry (not generic billboard trees).",
        "Apply ShadeMap-class ray–occluder tests.",
        "Combine with wind comfort for dual outdoor planning.",
    ]:
        add_para(tf, f"•  {it}", 13, False, DARK, 7)


def slide_pilot_pair(prs):
    s = blank_slide(prs)
    skyline_footer(s, prs)
    title_green(s, "Pilot Use Cases")
    subtitle(s, "Two science layers on one PolyU digital twin")

    cards = [
        (
            0.45,
            BLUE,
            "Wind-aware campus comfort",
            "Pedestrian-level CFD tracers for route and plaza screening.",
            [
                "1.5 m AGL tracers (turbo speed scale)",
                "Hourly HKO King's Park remap",
                "Tree LAD drag + building wakes",
            ],
        ),
        (
            6.85,
            ORANGE,
            "Shade-aware outdoor planning",
            "Geometric building + tree shadows for any HKT timestamp.",
            [
                "SunCalc solar position (PolyU lat/lon)",
                "LAZ solid crowns as occluders",
                "Daylight time slider / play-day loop",
            ],
        ),
    ]
    for left, accent, title, sub, bullets in cards:
        round_rect(s, left, 1.25, 6.0, 5.1, CARD_BG, accent, 1.5)
        tf = body_box(s, left + 0.25, 1.45, 5.5, 4.7)
        add_para(tf, title, 18, True, accent, 6)
        add_para(tf, sub, 13, False, MUTED, 12)
        for b in bullets:
            add_para(tf, f"•  {b}", 14, False, DARK, 8)


def slide_highlights(prs):
    s = blank_slide(prs)
    skyline_footer(s, prs)
    title_green(s, "Technical Highlights")

    blocks = [
        (
            0.4,
            TEAL,
            "1",
            "Multi-source campus twin",
            [
                "CSDI / LandsD footprints + heights",
                "OSM + LandsD 3D pedestrian network",
                "Segmented LAZ tree crowns",
                "CFD UVW package + HKO inlet remap",
            ],
        ),
        (
            4.55,
            GREEN,
            "2",
            "Science-based outdoor layers",
            [
                "Wind: urban CFD at pedestrian height",
                "Shade: direct-sun geometric occlusion",
                "Shared 3D scene for both layers",
                "Transparent equations for review",
            ],
        ),
        (
            8.7,
            PURPLE,
            "3",
            "Hong Kong–ready deployment",
            [
                "PolyU + Block Z domain focus",
                "HKO King's Park hourly Actions update",
                "Live dashboard (GitHub Pages)",
                "Methods documented for academic review",
            ],
        ),
    ]
    for left, color, num, title, items in blocks:
        top = 1.15
        round_rect(s, left, top, 3.95, 5.2, CARD_BG, LINE, 1.0)
        badge = s.shapes.add_shape(
            MSO_SHAPE.OVAL, Inches(left + 0.2), Inches(top + 0.25), Inches(0.38), Inches(0.38)
        )
        badge.fill.solid()
        badge.fill.fore_color.rgb = color
        badge.line.fill.background()
        set_run_text(badge.text_frame.paragraphs[0], num, 14, True, WHITE)
        badge.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
        tf = body_box(s, left + 0.2, top + 0.75, 3.55, 4.4)
        add_para(tf, title, 15, True, color, 10)
        for it in items:
            add_para(tf, f"•  {it}", 13, False, DARK, 7)


def slide_data(prs):
    s = blank_slide(prs)
    skyline_footer(s, prs)
    title_green(s, "Data Inventory")
    subtitle(s, "Inputs currently integrated into the twin")

    round_rect(s, 0.45, 1.20, 12.4, 4.35, RGBColor(0xEE, 0xF8, 0xF1), GREEN, 1.25)
    tf = body_box(s, 0.70, 1.40, 11.9, 4.0)
    add_para(tf, "Available datasets", 16, True, GREEN_DK, 8)
    have = [
        "LandsD / CSDI building footprints + heights (~1.5 km context)",
        "Pedestrian / road network (OSM + LandsD 3D Ped Network)",
        "Segmented individual-tree LAZ crowns (solid GLB + points)",
        "CFD wind UVW package (seed135 + Z-core air pad)",
        "Hourly HKO King's Park inlet remap (GitHub Actions)",
        "SunCalc solar ephemeris for PolyU (φ, λ, HKT)",
    ]
    for it in have:
        add_para(tf, f"•  {it}", 14, False, DARK, 5)

    # Concise next-step strip only
    round_rect(s, 0.45, 5.70, 12.4, 0.85, RGBColor(0xFF, 0xF6, 0xEE), ORANGE, 1.0)
    tf2 = body_box(s, 0.70, 5.82, 11.9, 0.65)
    add_para(
        tf2,
        "Priority gaps (concise): LAI / species validation for crown transmittance · ground-truth wind probes · optional full OpenFOAM re-solve for expanded domains.",
        13,
        False,
        DARK,
        0,
    )


def slide_method_wind(prs):
    s = blank_slide(prs)
    skyline_footer(s, prs)
    title_green(s, "Method — Wind Ventilation")
    subtitle(s, "Urban CFD field + pedestrian tracers · not a black-box heatmap")

    round_rect(s, 0.40, 1.20, 5.9, 3.55, GOLD_BG, GOLD, 1.25)
    wind3 = pick_img(IMG_WIND_DASH, IMG_WIND_PARTICLES, IMG_WIND_PARTICLES_FALLBACK, IMG_WIND_3D, IMG_WIND_3D_FALLBACK)
    try_picture(s, wind3, 0.55, 1.35, 5.6, 3.25, "Wind particle GIF")

    positions = [
        (6.50, 1.20, "1. Domain", "PolyU buildings + trees\nBlock Z north air pad"),
        (9.80, 1.20, "2. Physics", "RANS / canopy drag (LAD)\nSteady inlet wind"),
        (6.50, 3.05, "3. Inlet", "HKO King's Park\nrotate + scale UVW hourly"),
        (9.80, 3.05, "4. Output", "Tracers at 1.5 m AGL\nspeed colour (turbo)"),
    ]
    for left, top, title, body in positions:
        round_rect(s, left, top, 3.15, 1.70, CARD_BG, TEAL, 1.1)
        t = body_box(s, left + 0.12, top + 0.12, 2.9, 1.45)
        add_para(t, title, 13, True, TEAL, 3)
        for line in body.split("\n"):
            add_para(t, line, 12, False, DARK, 2)

    round_rect(s, 0.40, 4.95, 12.5, 1.55, GOLD_BG, GOLD, 1.25)
    et = body_box(s, 0.60, 5.10, 12.1, 1.30)
    add_para(et, "Hourly update (no full re-solve)", 13, True, DARK, 3)
    add_para(
        et,
        "UVW′ = R(Δθ) · UVW · (U_new / U_old)    with    Δθ = θ_HKO − θ_package",
        14,
        True,
        GREEN_DK,
        3,
    )
    add_para(
        et,
        "R = horizontal rotation from wind-from change; scale clipped for stability. Buildings and trees remain fixed geometry.",
        12,
        False,
        MUTED,
        0,
    )


def slide_method_shade(prs):
    s = blank_slide(prs)
    skyline_footer(s, prs)
    title_green(s, "Method — Building & Tree Shade")
    subtitle(s, "ShadeMap-class direct-sun geometric occlusion (clear-sky beam; not thermal CFD)")

    round_rect(s, 0.45, 1.20, 6.2, 5.15, CARD_BG, ORANGE, 1.25)
    t1 = body_box(s, 0.70, 1.40, 5.7, 4.8)
    add_para(t1, "Governing relations", 16, True, ORANGE, 8)
    add_para(t1, "Solar position (SunCalc / SPA-class)", 13, True, DARK, 4)
    add_para(t1, "sin α = sin φ sin δ + cos φ cos δ cos H", 13, False, GREEN_DK, 6)
    add_para(t1, "→ altitude α, azimuth A at PolyU (HKT)", 12, False, MUTED, 10)
    add_para(t1, "Shade test for ground point P", 13, True, DARK, 4)
    add_para(t1, "P shaded  ⇔  ray P + t ŝ  (t > 0) intersects an occluder", 13, False, GREEN_DK, 6)
    add_para(t1, "ŝ = unit vector toward the sun", 12, False, MUTED, 8)
    add_para(t1, "GPU shadow maps approximate the ray test in the dashboard.", 12, False, MUTED, 4)

    round_rect(s, 6.90, 1.20, 5.95, 5.15, CARD_BG, BLUE, 1.25)
    t2 = body_box(s, 7.15, 1.40, 5.5, 4.8)
    add_para(t2, "Layer inputs", 16, True, BLUE, 8)
    for it in [
        "Tree occluders: LAZ → solid crowns (GLB)",
        "Building occluders: LandsD footprint + height",
        "Receiver: campus ground plane",
        "Time control: HKT date + minute / play-day",
        "Site: φ = 22.3045°N, λ = 114.1795°E",
        "Scope: direct beam only (clear-sky geometry)",
    ]:
        add_para(t2, f"•  {it}", 14, False, DARK, 8)


def slide_pipeline_dashboard(prs):
    """Final slide: pipeline takeaway + updated dashboard visualizations."""
    s = blank_slide(prs)
    skyline_footer(s, prs)
    title_green(s, "Integrated Pipeline & Live Dashboard")
    subtitle(s, "Updated dashboard visualizations — wind tracers + time-resolved shade")

    # Two dashboard images
    round_rect(s, 0.35, 1.15, 6.25, 3.55, GOLD_BG, GOLD, 1.2)
    try_picture(s, IMG_DASH_TOP, 0.50, 1.30, 5.95, 3.25, "Dashboard — plan view")
    cap1 = body_box(s, 0.50, 4.55, 5.95, 0.30)
    set_run_text(cap1.paragraphs[0], "Plan view — wind field + building/tree shade", 11, False, MUTED)

    round_rect(s, 6.75, 1.15, 6.25, 3.55, GOLD_BG, GOLD, 1.2)
    try_picture(s, IMG_DASH_STREET, 6.90, 1.30, 5.95, 3.25, "Dashboard — street view")
    cap2 = body_box(s, 6.90, 4.55, 5.95, 0.30)
    set_run_text(cap2.paragraphs[0], "Oblique view — pedestrian tracers & canopy occlusion", 11, False, MUTED)

    # Pipeline steps compact
    steps = [
        "Ingest buildings, roads, LAZ crowns",
        "Load CFD UVW + HKO hourly remap",
        "Compute sun direction (HKT)",
        "Render tracers + cast shadows",
        "Publish via GitHub Pages",
    ]
    x = 0.35
    for i, st in enumerate(steps, 1):
        round_rect(s, x, 4.95, 2.45, 0.85, CARD_BG, TEAL, 1.0)
        t = body_box(s, x + 0.08, 5.05, 2.30, 0.70)
        add_para(t, f"{i}. {st}", 11, False, DARK, 0)
        x += 2.55

    foot = round_rect(s, 0.35, 5.95, 12.65, 0.70, CARD_BG, GREEN, 1.1)
    ft = body_box(s, 0.55, 6.05, 12.25, 0.55)
    add_para(
        ft,
        "Outcome: two science-based outdoor layers — wind ventilation and sun shade — on one PolyU digital twin, "
        "with transparent equations, measured trees, and live weather coupling.",
        12,
        False,
        DARK,
        0,
    )


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Ensure tree side view exists
    if not IMG_TREES_SIDE.exists():
        import subprocess
        import sys

        subprocess.check_call([sys.executable, str(ROOT / "scripts" / "render_trees_side_view.py")])

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    slide_use_case_wind(prs)
    slide_use_case_shade(prs)
    slide_pilot_pair(prs)
    slide_highlights(prs)
    slide_data(prs)
    slide_method_wind(prs)
    slide_method_shade(prs)
    slide_pipeline_dashboard(prs)

    try:
        prs.save(OUT)
        written = OUT
    except PermissionError:
        prs.save(OUT_ALT)
        written = OUT_ALT
        print(f"Primary PPT locked; wrote {written}")
    else:
        print(f"Wrote {written}")
    for label, p in [
        ("wind_orbit", IMG_WIND_DASH),
        ("shadow_day", IMG_SHADOW_DAY),
        ("trees_side", IMG_TREES_SIDE),
        ("dash_top", IMG_DASH_TOP),
        ("dash_street", IMG_DASH_STREET),
    ]:
        print(f"  {label}: {'OK' if p and Path(p).exists() else 'MISSING'} {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
