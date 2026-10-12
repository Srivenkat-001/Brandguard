"""Data-source connectors.

Every connector returns a SourceResult and NEVER raises: if a source is
unreachable, unconfigured, or rate-limited it reports status="unavailable"
with a readable message, and the scan carries on with the other sources.

  * FixtureSource      - offline demo feeds (JSON) so the prototype always runs
  * ITunesAppSource    - live Apple App Store search (public API, no key)
  * GooglePlaySource   - live Google Play search (needs `pip install google-play-scraper`)
  * SocialApiSource    - placeholder for X / Meta / Telegram APIs (needs credentials)

Adding a source = subclass Source and implement fetch().
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import logo as logomod
from .profile import BrandProfile
from .textmatch import generate_variants


@dataclass
class SourceResult:
    source: str
    kind: str                      # "social" | "app"
    status: str                    # "ok" | "unavailable"
    items: list[dict] = field(default_factory=list)
    message: str = ""
    elapsed: float = 0.0


class Source:
    name = "source"
    kind = "social"

    def fetch(self, brand: BrandProfile) -> SourceResult:  # pragma: no cover - interface
        raise NotImplementedError

    def safe_fetch(self, brand: BrandProfile) -> SourceResult:
        t0 = time.time()
        try:
            res = self.fetch(brand)
        except Exception as e:  # a connector must never break the scan
            res = SourceResult(self.name, self.kind, "unavailable", message=f"{type(e).__name__}: {e}")
        res.elapsed = round(time.time() - t0, 2)
        return res


def search_queries(brand: BrandProfile, limit: int = 10) -> list[str]:
    qs = [brand.name, *brand.aliases]
    qs += generate_variants(brand.name, limit=limit)
    seen, out = set(), []
    for q in qs:
        if q and q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out[:limit]


# ------------------------------------------------------------------ fixtures
class FixtureSource(Source):
    def __init__(self, name: str, kind: str, path: str | Path, platforms: set[str] | None = None):
        self.name, self.kind, self.path = name, kind, Path(path)
        self.platforms = platforms

    def fetch(self, brand: BrandProfile) -> SourceResult:
        if not self.path.exists():
            return SourceResult(self.name, self.kind, "unavailable", message=f"Feed not found: {self.path}")
        items = json.loads(self.path.read_text())
        key = "platform" if self.kind == "social" else "store"
        if self.platforms:
            items = [i for i in items if i.get(key) in self.platforms]
        base = self.path.parent
        img_key = "avatar" if self.kind == "social" else "icon"
        hash_key = "avatar_hash" if self.kind == "social" else "icon_hash"
        for it in items:
            p = base / it.get(img_key, "") if it.get(img_key) else None
            if p and p.exists():
                it[hash_key] = logomod.hash_image(p)
                it["_image_path"] = str(p)
        return SourceResult(self.name, self.kind, "ok", items, f"{len(items)} records")


# ------------------------------------------------------------------- live
class ITunesAppSource(Source):
    """Apple App Store via the public iTunes Search API (no credentials)."""
    name, kind = "Apple App Store (live)", "app"

    def __init__(self, country: str = "in", per_query: int = 15, max_queries: int = 8, icons: bool = True):
        self.country, self.per_query, self.max_queries, self.icons = country, per_query, max_queries, icons

    def fetch(self, brand: BrandProfile) -> SourceResult:
        import requests
        items, seen = [], set()
        for q in search_queries(brand, self.max_queries):
            r = requests.get("https://itunes.apple.com/search", timeout=8, params={
                "term": q, "entity": "software", "country": self.country, "limit": self.per_query})
            r.raise_for_status()
            for a in r.json().get("results", []):
                aid = a.get("bundleId") or (str(a["trackId"]) if a.get("trackId") else "")
                if not aid or aid in seen:
                    continue
                seen.add(aid)
                it = {"store": "app_store", "app_id": aid, "name": a.get("trackName", ""),
                      "developer": a.get("sellerName") or a.get("artistName", ""),
                      "developer_id": str(a.get("artistId", "")), "description": a.get("description", ""),
                      "installs": None, "rating": a.get("averageUserRating"),
                      "permissions": [], "url": a.get("trackViewUrl", "")}
                if self.icons and a.get("artworkUrl512"):
                    try:
                        img = requests.get(a["artworkUrl512"], timeout=6).content
                        it["icon_hash"] = logomod.hash_image(img)
                    except Exception:
                        pass
                items.append(it)
        return SourceResult(self.name, self.kind, "ok", items, f"{len(items)} apps from {len(seen)} unique results")


class GooglePlaySource(Source):
    """Google Play via the optional `google-play-scraper` package (unofficial; may be rate-limited)."""
    name, kind = "Google Play (live)", "app"

    def __init__(self, country: str = "in", lang: str = "en", per_query: int = 15, max_queries: int = 8):
        self.country, self.lang, self.per_query, self.max_queries = country, lang, per_query, max_queries

    def fetch(self, brand: BrandProfile) -> SourceResult:
        try:
            from google_play_scraper import search
        except ImportError:
            return SourceResult(self.name, self.kind, "unavailable",
                                message="Optional dependency missing: pip install google-play-scraper")
        import requests
        items, seen = [], set()
        for q in search_queries(brand, self.max_queries):
            for a in search(q, lang=self.lang, country=self.country, n_hits=self.per_query):
                if not a.get("appId") or a["appId"] in seen:
                    continue
                seen.add(a["appId"])
                it = {"store": "google_play", "app_id": a["appId"], "name": a.get("title", ""),
                      "developer": a.get("developer", ""), "developer_id": str(a.get("developerId", "")),
                      "description": a.get("description", "") or "", "installs": None,
                      "rating": a.get("score"), "permissions": [],
                      "url": f"https://play.google.com/store/apps/details?id={a['appId']}"}
                if a.get("icon"):
                    try:
                        it["icon_hash"] = logomod.hash_image(requests.get(a["icon"], timeout=6).content)
                    except Exception:
                        pass
                items.append(it)
        return SourceResult(self.name, self.kind, "ok", items, f"{len(items)} apps")


class SocialApiSource(Source):
    """Placeholder for licensed social APIs. Reports 'unavailable' until a token is configured.

    Social platforms have no free public search API, so production use plugs in an
    official API (X API, Meta Content Library, Telegram Bot/TDLib) or a data vendor
    by implementing `_search()` and setting the token environment variable.
    """
    kind = "social"

    def __init__(self, platform: str, env_var: str):
        self.platform, self.env_var = platform, env_var
        self.name = f"{platform.title()} (live API)"

    def fetch(self, brand: BrandProfile) -> SourceResult:
        if not os.environ.get(self.env_var):
            return SourceResult(self.name, self.kind, "unavailable",
                                message=f"No API credentials configured (set {self.env_var}). Showing other sources.")
        return SourceResult(self.name, self.kind, "unavailable",
                            message="Connector stub: implement _search() for this vendor.")


def demo_sources(data_dir: str | Path, domains: bool = False) -> list[Source]:
    d = Path(data_dir)
    out: list[Source] = [
        FixtureSource("Social feed (demo)", "social", d / "social_feed.json"),
        FixtureSource("App store feed (demo)", "app", d / "app_feed.json"),
        SocialApiSource("instagram", "META_TOKEN"),
    ]
    if domains:
        out.append(FixtureSource("Domain feed (demo)", "domain", d / "domain_feed.json"))
    return out


def live_sources(apps: bool = True, social: bool = True, domains: bool = True) -> list[Source]:
    out: list[Source] = []
    if apps:
        out += [ITunesAppSource(), GooglePlaySource()]
    if social:
        from .social_sources import live_social_sources
        out += live_social_sources()
    if domains:
        from .domain_sources import DomainScanSource
        out.append(DomainScanSource())
    return out
