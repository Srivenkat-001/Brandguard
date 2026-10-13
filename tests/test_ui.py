"""Tests for the visual layer (brandguard/ui.py) and the 'show originals in green' engine support."""
from pathlib import Path

from brandguard import ui
from brandguard.engine import rescan, run_scan
from brandguard.profile import BrandProfile
from brandguard.sources import demo_sources
from brandguard.storage import Store

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "data/demo"
HOSTILE = '<img src=x onerror=alert(1)><script>alert(2)</script> "quoted" $5 $6\nsecond line'


def _det(**kw):
    d = {"id": 1, "kind": "social", "source": "t", "platform": "x", "ref": "evil", "title": "Evil", "url": "",
         "score": 80, "level": "high", "status": "new", "evidence": {}, "reasons": [
             {"signal": "name", "points": 45, "detail": "Name is a look-alike"}]}
    d.update(kw)
    return d


# ------------------------------------------------------------------ safety
def test_esc_neutralises_html_newlines_and_math():
    out = ui.esc(HOSTILE)
    assert "<" not in out and ">" not in out and "\n" not in out and "$" not in out


def test_safe_url_allows_only_web_links():
    assert ui.safe_url("https://example.com/a") == "https://example.com/a"
    for bad in ["javascript:alert(1)", "data:text/html,x", "ftp://x.com", "//x.com", "", None, "not a url"]:
        assert ui.safe_url(bad) == "", bad


def test_threat_card_escapes_attacker_controlled_text():
    d = _det(title=HOSTILE, url="javascript:alert(1)",
             reasons=[{"signal": "name", "points": 45, "detail": HOSTILE}],
             evidence={"bio": HOSTILE, "followers": 3, "account_age_days": 2, "verified": False})
    out = ui.threat_card(d, "")
    assert "<img" not in out and "<script" not in out and "javascript:" not in out
    assert "&lt;img" in out


def test_cards_are_single_line_html():
    """Blank lines or indentation would break the HTML block when rendered through markdown."""
    for out in (ui.threat_card(_det(), ""), ui.original_card({"kind": "app", "platform": "google_play", "title": "A",
                                                              "detail": "d", "via": "official"}),
                ui.status_banner(ui.summarize([_det()], []), True), ui.legend()):
        assert "\n" not in out


# ------------------------------------------------------------- colour logic
def test_level_ranges_follow_detection_thresholds():
    assert ui.level_ranges() == {"high": "70–100", "medium": "40–69", "low": "25–39"}


def test_each_level_gets_its_own_colour_class_and_label():
    for lv, word in [("high", "HIGH"), ("medium", "MEDIUM"), ("low", "LOW")]:
        out = ui.threat_card(_det(level=lv), "")
        assert f"bg-lv-{lv}" in out and word in out
    assert "bg-lv-original" in ui.original_card({"kind": "social", "platform": "x", "title": "T", "detail": "", "via": "official"})


def test_summarize_ignores_dismissed_findings():
    dets = [_det(level="high"), _det(level="high", status="dismissed"), _det(level="low", status="confirmed")]
    c = ui.summarize(dets, [{"x": 1}])
    assert (c["high"], c["low"], c["original"], c["dismissed"], c["confirmed"], c["active"]) == (1, 1, 1, 1, 1, 2)


def test_status_banner_reflects_worst_threat():
    base = {"high": 0, "medium": 0, "low": 0, "original": 3, "dismissed": 0}
    assert "bg-lv-info" in ui.status_banner(base, scanned=False)
    assert "bg-lv-original" in ui.status_banner(base, scanned=True)
    assert "bg-lv-low" in ui.status_banner({**base, "low": 1}, True)
    assert "bg-lv-medium" in ui.status_banner({**base, "low": 1, "medium": 2}, True)
    assert "bg-lv-high" in ui.status_banner({**base, "low": 1, "medium": 2, "high": 1}, True)


def test_mixed_alphabet_detection():
    assert ui.lookalike_chars("V\u0435ridian Bank") and "Cyrillic" in ui.lookalike_chars("V\u0435ridian Bank")[0]
    assert ui.lookalike_chars("Veridian Bank") == []
    assert ui.lookalike_chars("\u0412\u0435\u0440\u0438") == []      # fully Cyrillic: not a mixed-script trick


# ------------------------------------------------- originals + rescan (engine)
def test_originals_are_collected_during_scan():
    brand = BrandProfile.load(DEMO / "brand.json")
    store = Store(":memory:")
    rep = run_scan(brand, demo_sources(DEMO, domains=True), store)
    assert len(rep.verified) == rep.summary["excluded_official"] + rep.summary["excluded_allowlisted"] > 0
    assert {v["via"] for v in rep.verified} == {"official"}
    stored = store.verified(brand.name)
    assert len(stored) == len(rep.verified)
    assert not {v["ref"] for v in stored} & {d.ref for d in rep.detections}   # an asset is never both


def test_allowlisted_items_show_as_approved_originals():
    brand = BrandProfile.load(DEMO / "brand.json")
    store = Store(":memory:")
    rep = rescan(brand, demo_sources(DEMO, domains=True), store)
    target = rep.detections[0]
    brand.allowlist.append(f"{target.kind}:{target.platform}:{target.ref}")
    rep2 = rescan(brand, demo_sources(DEMO, domains=True), store)
    assert target.ref not in {d.ref for d in rep2.detections}
    approved = [v for v in store.verified(brand.name) if v["via"] == "allowlist"]
    assert [v["ref"] for v in approved] == [target.ref]


def test_rescan_keeps_analyst_decisions():
    brand = BrandProfile.load(DEMO / "brand.json")
    store = Store(":memory:")
    rescan(brand, demo_sources(DEMO), store)
    dets = store.detections(brand.name)
    store.set_status(dets[0]["id"], "confirmed")
    store.set_status(dets[1]["id"], "dismissed")
    keys = [(d["kind"], d["platform"], d["ref"]) for d in dets[:2]]
    rescan(brand, demo_sources(DEMO), store)
    after = {(d["kind"], d["platform"], d["ref"]): d["status"] for d in store.detections(brand.name)}
    assert (after[keys[0]], after[keys[1]]) == ("confirmed", "dismissed")
    assert sum(1 for s in after.values() if s == "new") == len(after) - 2


def test_verified_store_roundtrip():
    store = Store(":memory:")
    rec = {"kind": "app", "source": "s", "platform": "google_play", "ref": "com.x", "title": "X", "via": "official",
           "detail": "d", "evidence": {"a": 1}}
    store.add_verified("B", rec)
    store.add_verified("B", rec)                      # same asset again: replaced, not duplicated
    assert len(store.verified("B")) == 1 and store.verified("B")[0]["evidence"] == {"a": 1}
    store.remove_verified("B", "app", "google_play", "com.x")
    assert store.verified("B") == []
