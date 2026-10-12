"""Social connector tests: HTTP is mocked, so they run offline."""
from pathlib import Path

from brandguard import social_sources as ss
from brandguard.engine import run_scan
from brandguard.profile import BrandProfile
from brandguard.storage import Store

BRAND = BrandProfile.load(Path(__file__).resolve().parent.parent / "data/demo/brand.json")


class R:
    def __init__(self, js=None, text="", code=200):
        self._j, self.text, self.status_code, self.content = js, text, code, b""

    def json(self):
        return self._j

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_bluesky_scam_profile_is_flagged(monkeypatch):
    monkeypatch.setattr(ss, "_http_get", lambda url, **kw: R({"actors": [{
        "handle": "veridian-bank-support.bsky.social", "displayName": "Veridian Bank Support",
        "description": "Send OTP for instant KYC update", "createdAt": "2026-09-30T00:00:00Z"}]}))
    rep = run_scan(BRAND, [ss.BlueskySource()], Store(":memory:"))
    assert rep.sources[0]["status"] == "ok" and rep.summary["flagged"] == 1


def test_blocked_source_is_unavailable_not_a_crash(monkeypatch):
    monkeypatch.setattr(ss, "_http_get", lambda url, **kw: R(code=403))
    rep = run_scan(BRAND, [ss.HandleProbeSource("tiktok"), ss.BlueskySource()], Store(":memory:"))
    assert [s["status"] for s in rep.sources] == ["unavailable", "unavailable"]


def test_keyed_sources_report_missing_key(monkeypatch):
    for v in ("YOUTUBE_API_KEY", "YOUTUBE_API_KEYS", "X_BEARER_TOKEN", "X_BEARER_TOKENS"):
        monkeypatch.delenv(v, raising=False)
    rep = run_scan(BRAND, [ss.YouTubeSource(), ss.XApiSource()], Store(":memory:"))
    assert all(s["status"] == "unavailable" and "set" in s["message"] for s in rep.sources)


def test_handle_candidates_are_valid():
    c = ss.handle_candidates(BRAND)
    assert "veridianbank" in c and all(3 <= len(x) <= 30 for x in c)


def test_key_pool_fails_over_to_next_key(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEYS", "k1,k2,k3")
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    ss.YOUTUBE_KEYS.reset()
    used = []

    def fake(url, **kw):
        k = kw["params"]["key"]
        used.append(k)
        if k == "k1":
            return R({"error": "quotaExceeded"}, text='{"reason":"quotaExceeded"}', code=403)
        return R({"items": [{"snippet": {"channelId": "UC1", "channelTitle": "Veridian Bank Support",
                                         "description": "send OTP for KYC", "publishedAt": "2026-10-01T00:00:00Z"}}]})
    monkeypatch.setattr(ss, "_http_get", fake)
    rep = run_scan(BRAND, [ss.YouTubeSource()], Store(":memory:"))
    assert rep.sources[0]["status"] == "ok" and rep.summary["flagged"] == 1
    assert "k1" in used and "k2" in used
    assert "2/3 keys" in rep.sources[0]["message"] or "available" in rep.sources[0]["message"]


def test_all_keys_exhausted_is_reported_not_crash(monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKENS", "a,b")
    ss.X_KEYS.reset()
    monkeypatch.setattr(ss, "_http_get", lambda url, **kw: R(code=429))
    rep = run_scan(BRAND, [ss.XApiSource()], Store(":memory:"))
    assert rep.sources[0]["status"] == "unavailable" and "out of quota" in rep.sources[0]["message"]
    ss.X_KEYS.reset()


def test_instagram_discovery_finds_lookalike_and_fails_over(monkeypatch):
    monkeypatch.setenv("IG_ACCOUNTS", "111:tokenAAAAAA,222:tokenBBBBBB")
    monkeypatch.delenv("IG_ACCOUNT", raising=False)
    ss.IG_KEYS.reset()

    def fake(url, **kw):
        tok = kw["params"]["access_token"]
        if tok == "tokenAAAAAA":
            return R({"error": {"code": 4, "message": "limit"}}, text="x", code=400)
        if "username(veridianbanksupport)" in kw["params"]["fields"]:
            return R({"business_discovery": {"username": "veridianbanksupport", "name": "Veridian Bank Support",
                      "biography": "Send OTP for instant KYC update", "followers_count": 90}}, text="x")
        return R({"error": {"code": 110, "message": "not found"}}, text="x", code=400)
    monkeypatch.setattr(ss, "_http_get", fake)
    rep = run_scan(BRAND, [ss.InstagramDiscoverySource()], Store(":memory:"))
    assert rep.sources[0]["status"] == "ok" and rep.summary["flagged"] == 1
    assert "tokenAAAAAA" not in rep.sources[0]["message"]
    ss.IG_KEYS.reset()


def test_instagram_not_configured_is_unavailable(monkeypatch):
    for v in ("IG_ACCOUNTS", "IG_ACCOUNT"):
        monkeypatch.delenv(v, raising=False)
    rep = run_scan(BRAND, [ss.InstagramDiscoverySource()], Store(":memory:"))
    assert rep.sources[0]["status"] == "unavailable"


# ------------------------------------------------------------------ domains
def test_domain_candidates_and_evaluation():
    from brandguard import domain_sources as dsrc
    from brandguard.detect import evaluate_domain, exclusion_reason
    c = dsrc.candidate_domains(BRAND)
    assert "veridianbank.xyz" in c and "veridianbank.com" not in c      # official domain never a candidate
    assert exclusion_reason(BRAND, "domain", {"domain": "veridianbank.co.in"}) == "official"
    assert exclusion_reason(BRAND, "domain", {"domain": "app.veridianbank.com"}) == "official"
    assert evaluate_domain(BRAND, {"domain": "veridianbakery.com", "live": True}) is None
    d = evaluate_domain(BRAND, {"domain": "veridianbank-rewards.com", "live": True, "first_seen_days": 5,
                                "title": "Claim", "page_text": "You have won! Enter OTP to claim your giveaway",
                                "has_login": True})
    assert d and d.level in ("high", "medium") and d.kind == "domain"


def test_domain_source_end_to_end_with_mocks(monkeypatch):
    from brandguard import domain_sources as dsrc
    monkeypatch.setattr(dsrc, "_resolve", lambda d: ["93.184.216.34"] if d == "veridianbank.xyz" else [])
    monkeypatch.setattr(dsrc, "_crt_domains", lambda flat: {"veridianbank-login.net": "2026-10-01T00:00:00"})
    monkeypatch.setattr(dsrc, "_page", lambda d, ips: {"title": "Veridian Bank", "page_text": "Update KYC now or account blocked",
                                                         "has_login": True})
    rep = run_scan(BRAND, [dsrc.DomainScanSource()], Store(":memory:"))
    refs = {d.ref for d in rep.detections}
    assert rep.sources[0]["status"] == "ok" and "veridianbank.xyz" in refs


def test_domain_source_survives_crt_and_dns_failure(monkeypatch):
    from brandguard import domain_sources as dsrc

    def boom(*a, **k):
        raise OSError("no network")
    monkeypatch.setattr(dsrc, "_resolve", boom)
    monkeypatch.setattr(dsrc, "_crt_domains", boom)
    rep = run_scan(BRAND, [dsrc.DomainScanSource()], Store(":memory:"))
    assert rep.sources[0]["status"] == "unavailable"


def test_private_ips_are_never_fetched():
    from brandguard import domain_sources as dsrc
    assert dsrc._page("evil.example", ["127.0.0.1"]) == {}
    assert dsrc._page("evil.example", ["10.0.0.5"]) == {}
