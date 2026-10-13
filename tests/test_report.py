"""Evidence PDF: valid output, safe with hostile / non-Latin text, one section per finding."""
import io
from pathlib import Path

import pytest
from pypdf import PdfReader

from brandguard.engine import rescan
from brandguard.profile import BrandProfile
from brandguard.report import build_report, clean
from brandguard.sources import demo_sources
from brandguard.storage import Store

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "data/demo"


@pytest.fixture(scope="module")
def scanned():
    b, s = BrandProfile.load(DEMO / "brand.json"), Store(":memory:")
    rescan(b, demo_sources(DEMO, domains=True), s)
    return b, s.detections(b.name)


def text(pdf: bytes) -> str:
    raw = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    return " ".join(raw.split())          # table labels wrap across lines; compare on flattened text


def test_single_report_has_the_evidence(scanned):
    b, dets = scanned
    d = dets[0]
    t = text(build_report(b, [d], root=ROOT))
    for must in (b.name, d["ref"], "Why it is an impersonation", "Observed content", "Visual comparison",
                 "Declaration", f"SCORE {int(d['score'])}"):
        assert must in t, must
    assert all(r["detail"][:25] in t for r in d["reasons"] if r["points"] > 0)


def test_many_findings_get_a_summary_and_a_section_each(scanned):
    b, dets = scanned
    t = text(build_report(b, dets, root=ROOT))
    assert "summary" in t and t.count("Declaration") == len(dets)


def test_every_demo_finding_renders(scanned):
    b, dets = scanned
    for d in dets:                       # social, app and domain findings all build
        assert build_report(b, [d], root=ROOT).startswith(b"%PDF")


def test_homoglyph_is_spelled_out_not_drawn(scanned):
    b, dets = scanned
    d = next(x for x in dets if "\u0435" in x["title"])
    t = text(build_report(b, [d], root=ROOT))
    assert "U+0435" in t and "Hidden look-alike letters" in t


def test_hostile_text_cannot_break_the_pdf(scanned):
    b, dets = scanned
    d = dict(dets[0], title="<b>unclosed <img src=x> & \U0001F600 \u202e", ref="<script>x</script>",
             evidence=dict(dets[0]["evidence"], bio="<para><font>" * 5 + " \U0001F4A5"))
    t = text(build_report(b, [d], root=ROOT))
    assert t and "<script>" in t          # shown literally as text, never interpreted


def test_missing_images_are_skipped(scanned):
    b, dets = scanned
    d = dict(dets[0], evidence=dict(dets[0]["evidence"], image_path="nope/missing.png"))
    assert "Visual comparison" not in text(build_report(b, [d], root=ROOT))


def test_clean_escapes_and_replaces():
    assert clean("a<b>&") == "a&lt;b&gt;&amp;" and clean("\u0435") == "&lt;U+0435&gt;"


def test_app_offers_pdf_buttons():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    next(b for b in at.button if b.label.startswith("Load demo")).click().run()
    next(b for b in at.button if "Run scan" in b.label).click().run()
    assert not at.exception
