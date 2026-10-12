from pathlib import Path

import pytest

from brandguard.engine import run_scan
from brandguard.profile import BrandProfile, OfficialAccount
from brandguard.sources import FixtureSource, SocialApiSource, Source, SourceResult, demo_sources
from brandguard.storage import Store
from brandguard.textmatch import lookalike

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "data/demo"
NAMES = ["Veridian Bank", "VeridianBank", "veridianbank", "Veridian"]


@pytest.fixture(scope="module")
def report():
    brand = BrandProfile.load(DEMO / "brand.json")
    return run_scan(brand, demo_sources(DEMO), Store(":memory:"))


# ---------------------------------------------------------- look-alike names
@pytest.mark.parametrize("name,kind", [
    ("VeridianBank", "spacing"), ("Veri dian Bank", "spacing"), ("veridianbnak", "swap"),
    ("Verldian Bank", "substitution"), ("V\u0435ridian Bank", "homoglyph"),
    ("Veridian Bank Support", "added words"), ("Bank Veridian", "word order"),
])
def test_lookalikes_are_caught(name, kind):
    r = lookalike(name, NAMES)
    assert r.hit, (name, r)
    assert kind in " ".join(r.kinds), r.kinds


@pytest.mark.parametrize("name", [
    "Veridian Bakery", "Veridian Credit Union", "Venetian Bank", "Veridian Valley Hiking Club",
    "Verde Bank", "Vertigo Bank", "Acme Bank",
])
def test_unrelated_names_are_not_flagged(name):
    assert not lookalike(name, NAMES).hit, name


# --------------------------------------------------------------- end to end
def test_official_assets_never_flagged(report):
    refs = {d.ref for d in report.detections}
    assert not refs & {"veridianbank", "veridianbankofficial", "com.veridianbank.mobile"}
    assert report.summary["excluded_official"] == 5


def test_expected_impersonators_found(report):
    refs = {d.ref for d in report.detections}
    for must in ["veridian_bank_support", "veridianbnak", "veridian1bank", "veridian_bank_helpdesk",
                 "com.vrdn.rewards2024", "com.veridian.bank.mobile2", "net.verldian.app",
                 "com.quickpay.vbpay"]:
        assert must in refs, must


def test_benign_lookalike_free_assets_not_flagged(report):
    refs = {d.ref for d in report.detections}
    for benign in ["veridianbakery", "veridiancu", "veridianbankfans", "venetianbank", "veridianhikers",
                   "com.veridianbakery.orders", "org.openmaps.atmfinder", "com.venetianbank.app"]:
        assert benign not in refs, benign


def test_spoofed_publisher_name_is_called_out(report):
    d = next(d for d in report.detections if d.ref == "com.quickpay.vbpay")
    assert any(r["signal"] == "publisher" and "not the official one" in r["detail"] for r in d.reasons)


def test_severity_ordering(report):
    top = report.detections[0]
    assert top.level == "high" and top.score >= 90
    assert all(a.score >= b.score for a, b in zip(report.detections, report.detections[1:]))


# ------------------------------------------------------- allowlist + profile
def test_allowlist_suppresses_a_finding():
    brand = BrandProfile.load(DEMO / "brand.json")
    brand.allowlist.append("social:x:veridian1bank")
    rep = run_scan(brand, demo_sources(DEMO))
    assert "veridian1bank" not in {d.ref for d in rep.detections}
    assert rep.summary["excluded_allowlisted"] == 1


def test_profile_validation():
    bad = BrandProfile(name="", domains=["not a domain"], logo_path="missing.png",
                       official_accounts=[OfficialAccount("myspace", "@x")])
    msgs = " | ".join(m for _, m in bad.validate())
    assert bad.has_errors()
    for frag in ["Brand name is required", "not a valid domain", "Logo file not found", "Unsupported platform"]:
        assert frag in msgs
    assert not BrandProfile.load(DEMO / "brand.json").has_errors()


def test_empty_profile_warns_that_official_assets_cannot_be_excluded():
    b = BrandProfile(name="Acme", domains=["acme.com"])
    assert any("nothing can be excluded" in m for _, m in b.validate())


# ------------------------------------------------------- graceful failure
class Exploding(Source):
    name, kind = "Exploding source", "social"
    def fetch(self, brand):
        raise TimeoutError("upstream timed out")


def test_unavailable_sources_do_not_break_the_scan():
    brand = BrandProfile.load(DEMO / "brand.json")
    srcs = [Exploding(), SocialApiSource("x", "NOT_SET_ENV_VAR"),
            FixtureSource("missing", "app", "/nope.json"), *demo_sources(DEMO)[:2]]
    rep = run_scan(brand, srcs)
    status = {s["source"]: s["status"] for s in rep.sources}
    assert status["Exploding source"] == "unavailable"
    assert status["X (live API)"] == "unavailable"
    assert status["missing"] == "unavailable"
    assert rep.summary["flagged"] == 11          # the healthy sources still produced results


def test_malformed_records_are_skipped_not_fatal():
    """Live feeds can return records with no app id / handle (seen with Google Play results)."""
    class Messy(Source):
        name, kind = "Messy app feed", "app"
        def fetch(self, brand):
            return SourceResult(self.name, self.kind, "ok", [
                {"store": "google_play", "app_id": None, "name": "Promoted"},
                {"store": "google_play", "app_id": "", "name": "Blank"},
                {"store": "google_play", "app_id": "com.veridian.bank.fake", "name": "Veridian Bank",
                 "developer": None, "description": None, "developer_id": None}])
    rep = run_scan(BrandProfile.load(DEMO / "brand.json"), [Messy()])
    assert rep.summary["skipped_malformed"] == 2
    assert [d.ref for d in rep.detections] == ["com.veridian.bank.fake"]
