"""Live social-media connectors.

Free / keyless  : Bluesky, Mastodon, Reddit (search), Telegram + TikTok + Instagram + Facebook (handle probing)
Needs a key     : YouTube (YOUTUBE_API_KEY, free quota), X (X_BEARER_TOKEN, paid API tier)

Honest note: Instagram, Facebook, LinkedIn and TikTok have NO public search API. For those the
`HandleProbeSource` checks whether look-alike handles exist by opening their public profile pages.
Those sites may block automated requests; when that happens the connector reports a readable
"unavailable/partial" status instead of failing the scan.
"""
from __future__ import annotations

import html
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import logo as logomod
from .profile import BrandProfile
from .sources import Source, SourceResult, search_queries
from .textmatch import generate_variants

UA = {"User-Agent": "Mozilla/5.0 (compatible; BrandGuard/1.0; brand-protection research)",
      "Accept-Language": "en"}
TIMEOUT = 8


# ---------------------------------------------------------------- helpers
def _http_get(url: str, **kw):
    import requests
    kw.setdefault("timeout", TIMEOUT)
    headers = {**UA, **kw.pop("headers", {})}
    return requests.get(url, headers=headers, **kw)


def _json(url: str, **kw) -> dict:
    r = _http_get(url, **kw)
    r.raise_for_status()
    return r.json()


def _strip_html(s: str | None) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def _age_days(ts) -> int | None:
    try:
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except Exception:
        return None


def _hash_url(url: str | None):
    if not url:
        return None
    try:
        r = _http_get(url, timeout=6)
        r.raise_for_status()
        return logomod.hash_image(r.content)
    except Exception:
        return None


def _links(*texts: str) -> list[str]:
    out = []
    for t in texts:
        out += re.findall(r"https?://[^\s\"'<>)]+", t or "")
    return list(dict.fromkeys(out))


def handle_candidates(brand: BrandProfile, limit: int = 40) -> list[str]:
    """Plausible impersonation handles: variants + brand + typical scam suffix/prefix words."""
    base = re.sub(r"[^a-z0-9]", "", brand.name.lower())
    words = ["official", "support", "care", "help", "india", "rewards", "customercare", "app"]
    cands = [base, re.sub(r"\s+", "_", brand.name.lower().strip())]
    cands += [f"{base}{w}" for w in words] + [f"{base}_{w}" for w in words] + [f"{w}{base}" for w in ("the", "real")]
    cands += [re.sub(r"[^a-zA-Z0-9_]", "", v) for v in generate_variants(brand.name, limit)]
    seen, out = set(), []
    for c in cands:
        c = c.strip("_")
        if 3 <= len(c) <= 30 and c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)
    return out[:limit]


def _parallel(fn, args: list, workers: int = 6):
    """Run fn over args; returns (results, errors). One failing call never kills the rest."""
    results, errors = [], []

    def run(a):
        try:
            return fn(a), None
        except Exception as e:
            return None, f"{type(e).__name__}: {str(e)[:120]}"

    with ThreadPoolExecutor(workers) as ex:
        for res, err in ex.map(run, args):
            if err:
                errors.append(err)
            elif res is not None:
                results.append(res)
    return results, errors


class _SearchSource(Source):
    """Template: run one search per query, merge, dedupe, report partial failures honestly."""
    kind = "social"
    max_queries = 6

    def search(self, query: str) -> list[dict]:  # pragma: no cover
        raise NotImplementedError

    def preflight(self) -> str | None:
        return None

    def fetch(self, brand: BrandProfile) -> SourceResult:
        problem = self.preflight()
        if problem:
            return SourceResult(self.name, self.kind, "unavailable", message=problem)
        queries = search_queries(brand, self.max_queries)
        batches, errors = _parallel(self.search, queries)
        if not batches and errors:
            return SourceResult(self.name, self.kind, "unavailable",
                                message=f"All searches failed ({errors[0]}). Network blocked or rate-limited?")
        items, seen = [], set()
        for b in batches:
            for it in b:
                key = it["handle"].lower()
                if key not in seen:
                    seen.add(key)
                    items.append(it)
        msg = f"{len(items)} accounts from {len(queries)} searches"
        pool = getattr(self, "pool", None)
        if pool:
            msg += f" [{pool.status()}]"
        if errors:
            msg += f" ({len(errors)} searches failed: {errors[0]})"
        return SourceResult(self.name, self.kind, "ok", items, msg)


# ---------------------------------------------------------------- Bluesky
class BlueskySource(_SearchSource):
    name = "Bluesky (live, no key)"

    def search(self, q):
        data = _json("https://public.api.bsky.app/xrpc/app.bsky.actor.searchActors", params={"q": q, "limit": 25})
        out = []
        for a in data.get("actors", []):
            bio = a.get("description") or ""
            out.append({"platform": "bluesky", "handle": a.get("handle", ""), "display_name": a.get("displayName") or "",
                        "type": "profile", "bio": bio, "followers": None,
                        "account_age_days": _age_days(a.get("createdAt")),
                        "verified": bool((a.get("verification") or {}).get("verifiedStatus") == "valid"),
                        "links": _links(bio), "avatar_hash": _hash_url(a.get("avatar")),
                        "url": f"https://bsky.app/profile/{a.get('handle', '')}"})
        return out


# ---------------------------------------------------------------- Mastodon
class MastodonSource(_SearchSource):
    def __init__(self, instance: str = "mastodon.social"):
        self.instance = instance
        self.name = f"Mastodon @{instance} (live, no key)"

    def search(self, q):
        data = _json(f"https://{self.instance}/api/v2/search",
                     params={"q": q, "type": "accounts", "limit": 20, "resolve": "false"})
        out = []
        for a in data.get("accounts", []):
            bio = _strip_html(a.get("note"))
            fields = " ".join(_strip_html(f.get("value")) for f in a.get("fields", []))
            out.append({"platform": "mastodon", "handle": a.get("acct", ""), "display_name": a.get("display_name") or "",
                        "type": "profile", "bio": bio, "followers": a.get("followers_count"),
                        "account_age_days": _age_days(a.get("created_at")), "verified": False,
                        "links": _links(bio, fields, a.get("url", "")) , "avatar_hash": _hash_url(a.get("avatar")),
                        "url": a.get("url", "")})
        return out


# ---------------------------------------------------------------- Reddit
class RedditSource(_SearchSource):
    name = "Reddit users (live, no key)"
    max_queries = 4

    def search(self, q):
        data = _json("https://www.reddit.com/search.json", params={"q": q, "type": "user", "limit": 15})
        out = []
        for c in data.get("data", {}).get("children", []):
            d = c.get("data", {})
            sub = d.get("subreddit") or {}
            bio = sub.get("public_description") or ""
            icon = (d.get("icon_img") or sub.get("icon_img") or "").split("?")[0]
            out.append({"platform": "reddit", "handle": d.get("name", ""), "display_name": sub.get("title") or d.get("name", ""),
                        "type": "profile", "bio": bio, "followers": sub.get("subscribers"),
                        "account_age_days": _age_days(d.get("created_utc")), "verified": bool(d.get("verified")),
                        "links": _links(bio), "avatar_hash": _hash_url(icon),
                        "url": f"https://www.reddit.com/user/{d.get('name', '')}"})
        return out


# ---------------------------------------------------------------- key pool
import threading
import time


class QuotaError(RuntimeError):
    """A key hit its quota / rate limit (try the next key)."""


class KeyPool:
    """Several API keys for one platform. When a key runs out of quota it is parked
    (cooldown) and the next key is used. Keys are read from the environment:

        YOUTUBE_API_KEYS="key1,key2,key3,key4,key5"   (comma / space / newline separated)
        YOUTUBE_API_KEY="key1"                        (single key also works)
    """

    def __init__(self, env_multi: str, env_single: str, cooldown: int = 6 * 3600):
        self.env_multi, self.env_single, self.cooldown = env_multi, env_single, cooldown
        self._parked: dict[str, float] = {}
        self._lock = threading.Lock()
        self._next = 0

    def keys(self) -> list[str]:
        raw = os.environ.get(self.env_multi, "") + "," + os.environ.get(self.env_single, "")
        return list(dict.fromkeys(k for k in re.split(r"[,\s;]+", raw) if k))

    def available(self) -> list[str]:
        now = time.time()
        with self._lock:
            return [k for k in self.keys() if self._parked.get(k, 0) <= now]

    def park(self, key: str):
        with self._lock:
            self._parked[key] = time.time() + self.cooldown

    def reset(self):
        with self._lock:
            self._parked.clear()

    def status(self) -> str:
        ks, av = self.keys(), self.available()
        return f"{len(av)}/{len(ks)} keys available"

    def call(self, fn):
        """fn(key) -> result. Fails over on QuotaError; other errors propagate (key redacted)."""
        tried = 0
        while True:
            av = self.available()
            if not av:
                raise QuotaError(f"all API keys are out of quota ({self.status()}); try again later or add keys")
            with self._lock:
                key = av[self._next % len(av)]
            try:
                return fn(key)
            except QuotaError:
                self.park(key)
                tried += 1
            except Exception as e:  # never leak a key into logs / UI
                msg = str(e)
                for part in [key, *key.split(":")]:
                    if len(part) > 6:
                        msg = msg.replace(part, "***")
                raise RuntimeError(msg) from None


def _keyed_json(url: str, is_quota, **kw) -> dict:
    r = _http_get(url, **kw)
    if is_quota(r):
        raise QuotaError(f"HTTP {r.status_code}")
    r.raise_for_status()
    return r.json()


YOUTUBE_KEYS = KeyPool("YOUTUBE_API_KEYS", "YOUTUBE_API_KEY")
X_KEYS = KeyPool("X_BEARER_TOKENS", "X_BEARER_TOKEN")


def _yt_quota(r) -> bool:
    return r.status_code == 429 or (r.status_code == 403 and any(
        w in (r.text or "").lower() for w in ("quotaexceeded", "dailylimitexceeded", "ratelimitexceeded")))


def _x_quota(r) -> bool:
    return r.status_code in (429, 402) or (r.status_code == 403 and any(
        w in (r.text or "").lower() for w in ("usagecap", "credits", "too many")))


# ---------------------------------------------------------------- YouTube (keys)
class YouTubeSource(_SearchSource):
    name = "YouTube (live API)"
    max_queries = 5
    pool = YOUTUBE_KEYS

    def preflight(self):
        if not self.pool.keys():
            return ("No API key (set YOUTUBE_API_KEYS=key1,key2,... or YOUTUBE_API_KEY; free from "
                    "Google Cloud Console). Showing other sources.")

    def search(self, q):
        s = self.pool.call(lambda key: _keyed_json(
            "https://www.googleapis.com/youtube/v3/search", _yt_quota,
            params={"part": "snippet", "type": "channel", "q": q, "maxResults": 15, "key": key}))
        out = []
        for it in s.get("items", []):
            sn = it.get("snippet", {})
            cid = sn.get("channelId") or it.get("id", {}).get("channelId", "")
            if not cid:
                continue
            thumb = (sn.get("thumbnails", {}).get("high") or sn.get("thumbnails", {}).get("default") or {}).get("url")
            bio = sn.get("description") or ""
            out.append({"platform": "youtube", "handle": cid, "display_name": sn.get("channelTitle") or "",
                        "type": "channel", "bio": bio, "followers": None,
                        "account_age_days": _age_days(sn.get("publishedAt")), "verified": False,
                        "links": _links(bio), "avatar_hash": _hash_url(thumb),
                        "url": f"https://www.youtube.com/channel/{cid}"})
        return out


# ---------------------------------------------------------------- X (tokens)
class XApiSource(_SearchSource):
    name = "X / Twitter (live API)"
    max_queries = 5
    pool = X_KEYS

    def preflight(self):
        if not self.pool.keys():
            return ("No API credentials (set X_BEARER_TOKENS=tok1,tok2,... or X_BEARER_TOKEN; "
                    "X reads are paid per request). Showing other sources.")

    def search(self, q):
        data = self.pool.call(lambda key: _keyed_json(
            "https://api.x.com/2/users/search", _x_quota,
            params={"query": q, "max_results": 20,
                    "user.fields": "created_at,description,public_metrics,verified,profile_image_url,url,entities"},
            headers={"Authorization": f"Bearer {key}"}))
        out = []
        for u in data.get("data", []):
            bio = u.get("description") or ""
            urls = [x.get("expanded_url") for x in (u.get("entities", {}).get("url", {}).get("urls", []) or [])]
            out.append({"platform": "x", "handle": u.get("username", ""), "display_name": u.get("name") or "",
                        "type": "profile", "bio": bio, "followers": (u.get("public_metrics") or {}).get("followers_count"),
                        "account_age_days": _age_days(u.get("created_at")), "verified": bool(u.get("verified")),
                        "links": [x for x in urls if x] + _links(bio),
                        "avatar_hash": _hash_url((u.get("profile_image_url") or "").replace("_normal", "_400x400")),
                        "url": f"https://x.com/{u.get('username', '')}"})
        return out


# ---------------------------------------------------------------- Instagram (official, free)
IG_KEYS = KeyPool("IG_ACCOUNTS", "IG_ACCOUNT")
_IG_RATE_CODES = {4, 17, 32, 613, 80002, 80004}


class InstagramDiscoverySource(Source):
    """Official Instagram Graph API 'Business Discovery' (free).

    Looks up exact usernames of OTHER Instagram *Business or Creator* accounts using your own
    Business/Creator account as the viewer. We feed it the look-alike handles from
    handle_candidates(). Personal accounts are not visible to this API.

    Config:  IG_ACCOUNTS="IG_USER_ID:ACCESS_TOKEN,IG_USER_ID2:TOKEN2,..."   (one pair per team member)
    """
    kind = "social"
    pool = IG_KEYS

    def __init__(self, max_handles: int = 30):
        self.max_handles = max_handles
        self.name = "Instagram (official Graph API)"

    def _lookup(self, handle: str):
        fields = ("business_discovery.username(%s){username,name,biography,followers_count,"
                  "media_count,profile_picture_url,website}" % handle)

        def one(pair: str):
            uid, _, token = pair.partition(":")
            ver = os.environ.get("IG_GRAPH_VERSION", "").strip("/")
            base = f"https://graph.facebook.com/{ver + '/' if ver else ''}{uid}"
            r = _http_get(base, params={"fields": fields, "access_token": token})
            try:
                body = r.json() if r.text or r.status_code else {}
            except Exception:
                body = {}
            err = (body or {}).get("error") if isinstance(body, dict) else None
            if r.status_code == 429 or (err and err.get("code") in _IG_RATE_CODES):
                raise QuotaError("rate limited")
            if err and err.get("code") == 190:
                raise RuntimeError("access token invalid or expired (code 190)")
            if err and err.get("code") in (10, 200):
                raise RuntimeError(f"permission problem: {err.get('message', '')[:100]}")
            if err or r.status_code >= 400:
                return None            # username not found / not a Business or Creator account
            return body.get("business_discovery")

        d = self.pool.call(one)
        if not d:
            return None
        bio = d.get("biography") or ""
        user = d.get("username") or handle
        return {"platform": "instagram", "handle": user, "display_name": d.get("name") or "",
                "type": "profile", "bio": bio, "followers": d.get("followers_count"),
                "account_age_days": None, "verified": None,
                "links": ([d["website"]] if d.get("website") else []) + _links(bio),
                "avatar_hash": _hash_url(d.get("profile_picture_url")),
                "url": f"https://www.instagram.com/{user}/"}

    def fetch(self, brand: BrandProfile) -> SourceResult:
        if not self.pool.keys():
            return SourceResult(self.name, self.kind, "unavailable", message=(
                "Not configured. Set IG_ACCOUNTS=IG_USER_ID:ACCESS_TOKEN (comma-separate several). "
                "Needs an Instagram Business/Creator account linked to a Facebook Page. Showing other sources."))
        cands = handle_candidates(brand, self.max_handles)
        found, errors = _parallel(self._lookup, cands, workers=4)
        if not found and errors:
            return SourceResult(self.name, self.kind, "unavailable", message=f"{errors[0]} [{self.pool.status()}]")
        msg = (f"{len(found)} Business/Creator look-alikes out of {len(cands)} handles checked "
               f"[{self.pool.status()}]; personal accounts are invisible to this API")
        if errors:
            msg += f" ({len(errors)} lookups failed: {errors[0]})"
        return SourceResult(self.name, self.kind, "ok", found, msg)


# ------------------------------------------------- handle probing (no search API)
def _meta(page: str, prop: str) -> str:
    m = (re.search(rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]+content=["\']([^"\']*)', page, re.I)
         or re.search(rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']{prop}["\']', page, re.I))
    return html.unescape(m.group(1)).strip() if m else ""


_LOGIN_WALL = re.compile(r"log in|login|sign up|instagram$|^facebook$|couldn.t find|page not found|not available", re.I)

PROBES = {
    # platform: (url template, existence check)
    "telegram": ("https://t.me/{h}", lambda p, t, d: "tgme_page_title" in p),
    "tiktok": ("https://www.tiktok.com/@{h}", lambda p, t, d: bool(t) and not _LOGIN_WALL.search(t)),
    "instagram": ("https://www.instagram.com/{h}/", lambda p, t, d: bool(t) and "@" in t and not _LOGIN_WALL.search(t)),
    "facebook": ("https://www.facebook.com/{h}", lambda p, t, d: bool(t) and not _LOGIN_WALL.search(t)),
}


class HandleProbeSource(Source):
    """Checks whether look-alike handles exist by opening public profile pages.

    There is no search API for these platforms, so we generate likely impersonation handles
    and see which ones exist. Blocked / login-walled responses are counted and reported."""
    kind = "social"

    def __init__(self, platform: str, max_handles: int = 30):
        if platform not in PROBES:
            raise ValueError(f"Unsupported platform: {platform}")
        self.platform, self.max_handles = platform, max_handles
        self.name = f"{platform.title()} (handle probe, no key)"

    def _probe(self, handle: str):
        url_t, exists = PROBES[self.platform]
        url = url_t.format(h=handle)
        r = _http_get(url, allow_redirects=True)
        if r.status_code == 404:
            return None
        if r.status_code in (401, 403, 429, 999):
            raise RuntimeError(f"blocked (HTTP {r.status_code})")
        r.raise_for_status()
        page = r.text
        title, desc = _meta(page, "og:title"), _meta(page, "og:description")
        if self.platform == "telegram":
            m = re.search(r'tgme_page_title[^>]*>\s*(?:<span[^>]*>)?([^<]+)', page)
            title = html.unescape(m.group(1)).strip() if m else title
            m = re.search(r'tgme_page_description[^>]*>(.*?)</div>', page, re.S)
            desc = _strip_html(m.group(1)) if m else desc
        if not exists(page, title, desc):
            return None
        return {"platform": self.platform, "handle": handle, "display_name": title, "type": "profile",
                "bio": desc, "followers": None, "account_age_days": None, "verified": None,
                "links": _links(desc), "avatar_hash": _hash_url(_meta(page, "og:image")), "url": url}

    def fetch(self, brand: BrandProfile) -> SourceResult:
        cands = handle_candidates(brand, self.max_handles)
        found, errors = _parallel(self._probe, cands, workers=5)
        if not found and len(errors) >= max(1, len(cands) // 2):
            return SourceResult(self.name, self.kind, "unavailable",
                                message=f"{self.platform.title()} blocked automated lookups ({errors[0]}). "
                                        "Use an official API or a data vendor for this platform.")
        msg = f"{len(found)} existing look-alike handles out of {len(cands)} checked"
        if errors:
            msg += f" ({len(errors)} lookups blocked/failed)"
        return SourceResult(self.name, self.kind, "ok", found, msg)


def live_social_sources() -> list[Source]:
    ig = InstagramDiscoverySource() if IG_KEYS.keys() else HandleProbeSource("instagram")
    return [BlueskySource(), MastodonSource(), RedditSource(), YouTubeSource(), XApiSource(), ig,
            HandleProbeSource("telegram"), HandleProbeSource("tiktok"), HandleProbeSource("facebook")]
