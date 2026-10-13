"""Render the dashboard's visual layer to a static HTML file (no Streamlit needed).

    python scripts/preview_ui.py            # writes docs/ui_preview.html
    python scripts/preview_ui.py --png      # also writes docs/ui_preview.png (needs `pip install playwright`)

Uses the same CSS and HTML builders as app.py on real demo-scan data. Streamlit's own widgets
(tabs, buttons) are drawn as plain stand-ins; run `streamlit run app.py` to see the real thing.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brandguard import ui                                   # noqa: E402
from brandguard.engine import rescan                        # noqa: E402
from brandguard.profile import BrandProfile                 # noqa: E402
from brandguard.sources import demo_sources                 # noqa: E402
from brandguard.storage import Store                        # noqa: E402

DEMO = ROOT / "data" / "demo"


def build(expand: bool = False, compact: bool = False) -> str:
    brand = BrandProfile.load(DEMO / "brand.json")
    store = Store(":memory:")
    rep = rescan(brand, demo_sources(DEMO, domains=True), store)
    dets, ver = store.detections(brand.name), store.verified(brand.name)
    counts = ui.summarize(dets, ver)
    logo = ui.thumb(brand.logo_file())

    def card(level, ident, inner, buttons):
        btns = "".join(f'<span class="bg-fakebtn{" pri" if p else ""}">{t}</span>' for t, p in buttons)
        return (f'<div class="st-key-{ui.card_class(level, ident)}" style="margin:0 0 12px">{inner}'
                f'<div style="margin-top:10px">{btns}</div></div>')

    body = [ui.hero(brand.name, logo), ui.status_banner(counts, True), ui.distribution(counts), ui.tiles(counts),
            ui.section("Threats", counts["active"], "neutral", "most dangerous first")]
    if compact:        # a short, representative slice for the README screenshot
        pick = [dets[0], dets[1]] + [next(d for d in dets if d["level"] == lv) for lv in ("medium", "low")
                                      if any(d["level"] == lv for d in dets)]
        dets, ver = pick, ver[:3]
    for i, d in enumerate(dets):
        inner = ui.threat_card(d, logo)
        if expand and i == 0:
            inner = inner.replace('<details class="bg-more">', '<details class="bg-more" open>')
        body.append(card(d["level"], d["id"], inner,
                         [("✔ Confirm threat", True), ("Dismiss", False), ("Mark as legitimate", False)]))
    body.append(ui.section("Original", len(ver), "original", "your verified assets, never flagged"))
    for v in ver:
        body.append(card("original", v["id"], ui.original_card(v),
                         [("Remove approval", False)] if v["via"] == "allowlist" else []))
    if not compact:
        body.append(ui.section("Scan details", None, "info"))
        body += [ui.funnel(rep.summary), ui.sources(rep.sources)]
        body.append(ui.section("Brand profile", None, "original"))
        body.append(ui.assets_panel(brand, logo))
    page = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Brand Guard UI preview</title>" + ui.CSS +
            "<body style=\"margin:0;background:#F6F7FB;font-family:'Source Sans Pro',-apple-system,'Segoe UI',Roboto,sans-serif\">"
            "<div class=block-container style='margin:0 auto;padding:24px 28px'>" + "".join(body) + "</div></body>")
    return page


if __name__ == "__main__":
    out = ROOT / "docs"
    out.mkdir(exist_ok=True)
    (out / "ui_preview.html").write_text(build(), encoding="utf-8")
    print("wrote", out / "ui_preview.html")
    if "--png" in sys.argv:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1240, "height": 900}, device_scale_factor=1.5)
            (out / "_hero.html").write_text(build(expand=True, compact=True), encoding="utf-8")
            pg.goto((out / "_hero.html").as_uri())
            pg.screenshot(path=str(out / "ui_preview.png"), full_page=True)
            b.close()
        (out / "_hero.html").unlink()
        print("wrote", out / "ui_preview.png")
