"""Detection logic: turn a candidate social profile / app into a scored, explainable finding.

Design principles
  * Official assets are excluded BEFORE scoring (brand profile + analyst allowlist).
  * An "identity signal" (look-alike name, logo copy, look-alike domain, or brand
    mention + scam text / publisher mismatch) is REQUIRED. Scammy-but-unrelated
    accounts and benign look-alike-free accounts are never reported.
  * Weighted signals, each with a human-readable reason and its point value.
  * Booster signals (new account, few followers, risky permissions) only add
    points once an identity signal exists, so they can never flag something alone.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urlparse

from . import logo as logomod
from .profile import BrandProfile, norm_domain, norm_handle, norm_platform
from .textmatch import lookalike, mentions_brand, tokens

LEVELS = [(70, "high"), (40, "medium"), (25, "low")]
REPORT_THRESHOLD = 25

SHORTENERS = {"bit.ly", "tinyurl.com", "cutt.ly", "t.co", "goo.gl", "rb.gy", "is.gd", "shorturl.at", "ow.ly"}
MESSAGING = {"wa.me", "wa.link", "t.me", "api.whatsapp.com", "chat.whatsapp.com"}

SCAM_PATTERNS = [
    (r"giveaway|you (have )?won|lucky draw|claim (your |now)|claim\b.*\b(prize|reward)", "giveaway / prize bait"),
    (r"\b(otp|cvv|pin)\b|card number|account number", "asks for OTP / card / account details"),
    (r"\bkyc\b|account (is )?(blocked|suspended|frozen)|verify (your )?account|reactivate", "KYC / account-block pretext"),
    (r"customer care|helpline|toll[- ]?free|24 ?x ?7", "fake customer-care contact"),
    (r"whatsapp|telegram|dm (us|me)|text us on", "pushes chat / DM contact"),
    (r"work from home|earn rs|registration fee|per day|guaranteed returns|double your|investment (plan|scheme)", "job / investment scam"),
    (r"free (coins|money|recharge|cash)|unlimited (coins|money|rewards)|\bhack\b|\bmod apk\b|cracked|generator|cashback", "too-good-to-be-true offer"),
    (r"login with|sign in with your (card|debit|credit)|enter your (card|pin|password)", "credential-harvesting prompt"),
]
HIGH_RISK_PERMS = {"READ_SMS", "SEND_SMS", "RECEIVE_SMS", "SYSTEM_ALERT_WINDOW",
                   "BIND_ACCESSIBILITY_SERVICE", "REQUEST_INSTALL_PACKAGES", "READ_CALL_LOG",
                   "BIND_DEVICE_ADMIN", "READ_CONTACTS"}
_STOP = set("the a an and or of to for in on with your you our is are be by at from as it this that".split())


@dataclass
class Detection:
    kind: str                       # "social" | "app" | "domain"
    source: str
    platform: str
    ref: str                        # handle or app id
    title: str
    score: int
    level: str
    reasons: list[dict] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    url: str = ""


def level_for(score: int) -> str:
    for cut, name in LEVELS:
        if score >= cut:
            return name
    return "none"


# ------------------------------------------------------------------ helpers
def scam_language(text: str) -> tuple[float, list[str]]:
    t = (text or "").lower()
    hits = [label for pat, label in SCAM_PATTERNS if re.search(pat, t)]
    n = len(hits)
    return (0.0 if n == 0 else 0.5 if n == 1 else 0.8 if n == 2 else 1.0), hits


def _host(url: str) -> str:
    u = url if "//" in url else "//" + url
    return (urlparse(u).hostname or "").lower().removeprefix("www.")


def _reg_domain(host: str) -> str:
    p = host.split(".")
    if len(p) >= 3 and len(p[-1]) == 2 and p[-2] in {"co", "com", "org", "net", "gov", "ac"}:
        return ".".join(p[-3:])
    return ".".join(p[-2:])


def analyze_links(brand: BrandProfile, links: list[str]) -> list[dict]:
    """Classify each outbound link: official | lookalike_domain | shortener | messaging | other."""
    official = {norm_domain(d) for d in brand.domains}
    out = []
    for link in links or []:
        host = _host(link)
        if not host:
            continue
        reg = _reg_domain(host)
        if reg in official or any(host == d or host.endswith("." + d) for d in official):
            out.append({"url": link, "type": "official"})
        elif host in SHORTENERS:
            out.append({"url": link, "type": "shortener"})
        elif host in MESSAGING:
            out.append({"url": link, "type": "messaging"})
        else:
            lk = lookalike(reg.split(".")[0], brand.match_names())
            out.append({"url": link, "type": "lookalike_domain" if lk.hit else "other",
                        "look": lk.describe(), "score": lk.score})
    return out


def _bow(text: str) -> Counter:
    return Counter(w for w in re.findall(r"[a-z]+", (text or "").lower()) if w not in _STOP and len(w) > 2)


def text_similarity(a: str, b: str) -> float:
    A, B = _bow(a), _bow(b)
    if not A or not B:
        return 0.0
    dot = sum(A[k] * B[k] for k in A.keys() & B.keys())
    return dot / (math.sqrt(sum(v * v for v in A.values())) * math.sqrt(sum(v * v for v in B.values())))


def brand_logo_hash(brand: BrandProfile):
    f = brand.logo_file()
    return logomod.hash_image(f) if f else None


def _add(reasons: list[dict], signal: str, points: float, detail: str):
    if points > 0:
        reasons.append({"signal": signal, "points": round(points), "detail": detail})


# --------------------------------------------------------------- exclusions
def exclusion_reason(brand: BrandProfile, kind: str, item: dict) -> str | None:
    """Return why an item must NOT be flagged ('official' / 'allowlisted'), else None."""
    if kind == "social":
        if brand.is_official_account(item["platform"], item["handle"]):
            return "official"
        if brand.is_allowlisted("social", item["platform"], norm_handle(item["handle"])):
            return "allowlisted"
    elif kind == "domain":
        official = {norm_domain(d) for d in brand.domains}
        dom = norm_domain(item["domain"])
        if dom in official or any(dom.endswith("." + o) for o in official):
            return "official"
        if brand.is_allowlisted("domain", "web", dom):
            return "allowlisted"
    else:
        if brand.is_official_app(item["app_id"], item.get("developer_id", "")):
            return "official"
        if brand.is_allowlisted("app", item["store"], item["app_id"]):
            return "allowlisted"
    return None


# ------------------------------------------------------------------- social
def evaluate_social(brand: BrandProfile, item: dict, b_hash, source: str = "") -> Detection | None:
    names = brand.match_names()
    platform, handle = norm_platform(item["platform"]), norm_handle(item["handle"])
    reasons: list[dict] = []
    identity = False

    ln = max((lookalike(item.get("display_name", ""), names), lookalike(handle, names)),
             key=lambda r: r.score)
    if ln.score > 0:
        _add(reasons, "name", 45 * ln.score, f"Name/handle is a look-alike: {ln.describe()}")
        identity = identity or ln.hit

    lg = logomod.compare(b_hash, item.get("avatar_hash"))
    if lg.verdict == "match":
        _add(reasons, "logo", 25, f"Profile image is a near-copy of the official logo (similarity {lg.similarity:.0%})")
        identity = True
    elif lg.verdict == "near":
        _add(reasons, "logo", 10, f"Profile image resembles the official logo (similarity {lg.similarity:.0%})")

    text = " ".join([item.get("bio", ""), item.get("recent_posts", "")])
    sc, hits = scam_language(text)
    if hits:
        _add(reasons, "scam_text", 25 * sc, "Scam-style language: " + "; ".join(hits))
        if mentions_brand(text, names) or ln.score >= 0.3:
            identity = True
            if ln.score < 0.5:
                _add(reasons, "brand_mention", 8, "Uses the brand name inside scam-style text")

    links = analyze_links(brand, item.get("links", []))
    for l in links:
        if l["type"] == "lookalike_domain":
            _add(reasons, "domain", 20 * l["score"], f"Links to look-alike domain {l['url']} ({l['look']})")
            identity = True
    if identity:
        for l in links:
            if l["type"] in ("shortener", "messaging"):
                _add(reasons, "link", 5, f"Links to {l['type']} URL {l['url']}")
                break

    if not identity:
        return None

    boost = 0
    if item.get("account_age_days") is not None and item["account_age_days"] < 90:
        boost += 4
        _add(reasons, "account_age", 4, f"New account ({item['account_age_days']} days old)")
    if item.get("followers") is not None and item["followers"] < 2000:
        boost += 2
        _add(reasons, "followers", 2, f"Small following ({item['followers']:,})")
    if item.get("verified") is False:
        _add(reasons, "verified", 2, "Not verified")

    score = min(100, sum(r["points"] for r in reasons))
    return Detection(
        kind="social", source=source, platform=platform, ref=handle,
        title=f"{item.get('display_name') or handle} (@{handle})", score=score, level=level_for(score),
        reasons=sorted(reasons, key=lambda r: -r["points"]),
        evidence={"type": item.get("type", "profile"), "bio": item.get("bio", ""),
                  "followers": item.get("followers"), "account_age_days": item.get("account_age_days"),
                  "verified": item.get("verified"), "links": links,
                  "image_path": item.get("_image_path", ""),
                  "logo": {"verdict": lg.verdict, "similarity": lg.similarity}},
        url=item.get("url", ""),
    )


# ------------------------------------------------------------------ domains
ABUSE_TLDS = {"xyz", "top", "online", "site", "click", "icu", "shop", "live", "club", "support",
              "help", "cfd", "sbs", "work", "rest", "buzz", "monster", "info"}


def evaluate_domain(brand: BrandProfile, item: dict, b_hash=None, source: str = "") -> Detection | None:
    names = brand.match_names()
    dom = norm_domain(item["domain"])
    reg = _reg_domain(dom)
    label, tld = reg.split(".", 1)[0], reg.split(".", 1)[-1]
    reasons: list[dict] = []
    identity = False

    ln = lookalike(label, names)
    official_labels = {_reg_domain(norm_domain(d)).split(".")[0] for d in brand.domains}
    if label in official_labels:
        _add(reasons, "name", 40, f"Same name as your official domain but a different ending (.{tld})")
        identity = True
    elif ln.score > 0:
        _add(reasons, "name", 40 * ln.score, f"Domain name is a look-alike: {ln.describe()}")
        identity = identity or ln.hit

    text = " ".join([item.get("title", ""), item.get("page_text", "")])
    sc, hits = scam_language(text)
    brand_in_page = mentions_brand(text, names)
    if hits:
        _add(reasons, "scam_text", 25 * sc, "Website uses scam-style language: " + "; ".join(hits))
        if brand_in_page or ln.score >= 0.3:
            identity = True
    if item.get("has_login") and (brand_in_page or ln.hit or identity):
        _add(reasons, "login_form", 10, "Page has a password / OTP form while using the brand name")

    if not identity:
        return None

    age = item.get("first_seen_days")
    if age is not None and age < 30:
        _add(reasons, "new_domain", 12, f"Certificate first issued only {age} days ago")
    elif age is not None and age < 90:
        _add(reasons, "new_domain", 8, f"Certificate first issued {age} days ago")
    if tld.split(".")[-1] in ABUSE_TLDS:
        _add(reasons, "tld", 4, f"Ending .{tld} is commonly abused for scam sites")

    score = sum(r["points"] for r in reasons)
    if not item.get("live", True):
        score = int(score * 0.7)
        reasons.append({"signal": "not_live", "points": 0, "detail": "Does not currently resolve (certificate/record only): score reduced"})
    score = min(100, score)
    return Detection(
        kind="domain", source=source, platform="web", ref=dom, title=dom, score=score, level=level_for(score),
        reasons=sorted(reasons, key=lambda r: -r["points"]),
        evidence={"title": item.get("title", ""), "page_text": item.get("page_text", "")[:300],
                  "sources": item.get("sources", []), "ips": item.get("ips", []),
                  "first_seen_days": age, "has_login": item.get("has_login", False), "live": item.get("live", True)},
        url=item.get("url", f"https://{dom}"))


# --------------------------------------------------------------------- apps
def _package_name(app_id: str) -> str:
    parts = [p for p in re.split(r"[._]", (app_id or "").lower())
             if p and p not in {"com", "org", "net", "io", "app", "android", "ios"}]
    return " ".join(parts)


def evaluate_app(brand: BrandProfile, item: dict, b_hash, source: str = "") -> Detection | None:
    names = brand.match_names()
    store, app_id = norm_platform(item["store"]), item["app_id"]
    reasons: list[dict] = []
    identity = False

    ln = max((lookalike(item.get("name", ""), names), lookalike(_package_name(app_id), names)),
             key=lambda r: r.score)
    if ln.score > 0:
        _add(reasons, "name", 40 * ln.score, f"App name / package is a look-alike: {ln.describe()}")
        identity = identity or ln.hit

    lg = logomod.compare(b_hash, item.get("icon_hash"))
    if lg.verdict == "match":
        _add(reasons, "icon", 25, f"App icon is a near-copy of the official logo (similarity {lg.similarity:.0%})")
        identity = True
    elif lg.verdict == "near":
        _add(reasons, "icon", 10, f"App icon resembles the official logo (similarity {lg.similarity:.0%})")

    desc = item.get("description", "")
    mention = mentions_brand(desc, names)
    sim = text_similarity(desc, brand.description + " " + " ".join(brand.keywords))
    dev, dev_id = item.get("developer", ""), str(item.get("developer_id", ""))
    dev_name_official = brand.developer_name_is_official(dev)

    if mention:
        identity = identity or True
    if not identity:
        return None

    # Publisher assessment (the official developer id would already have been excluded)
    if dev_name_official and dev_id:
        _add(reasons, "publisher", 20, f"Publisher name '{dev}' copies the official developer, "
                                       f"but the developer id ({dev_id}) is not the official one")
    elif dev_name_official:
        pass   # cannot verify without an id; do not penalise
    else:
        _add(reasons, "publisher", 15, f"Publisher '{dev or 'unknown'}' is not an official developer")
        dl = lookalike(dev, names)
        if dl.hit:
            _add(reasons, "publisher_name", 5, f"Publisher name imitates the brand: {dl.describe()}")

    if mention:
        _add(reasons, "description_mention", 5, "Store description names the brand")
    if sim >= 0.8:
        _add(reasons, "description", 10, f"Description is almost identical to the official listing ({sim:.0%} similar)")
    elif sim >= 0.25:
        _add(reasons, "description", 10 * min(1, sim / 0.6), f"Description resembles the official listing ({sim:.0%} similar)")

    sc, hits = scam_language(desc)
    if hits:
        _add(reasons, "risky_text", 10 * sc, "Risky wording: " + "; ".join(hits))
    perms = sorted(HIGH_RISK_PERMS & set(item.get("permissions") or []))
    if len(perms) >= 2:
        _add(reasons, "permissions", 8, "Requests high-risk permissions: " + ", ".join(perms))
    elif perms:
        _add(reasons, "permissions", 3, "Requests a high-risk permission: " + perms[0])
    if item.get("installs") is not None and item["installs"] < 1000:
        _add(reasons, "installs", 3, f"Very few installs ({item['installs']:,})")

    score = min(100, sum(r["points"] for r in reasons))
    return Detection(
        kind="app", source=source, platform=store, ref=app_id,
        title=item.get("name") or app_id, score=score, level=level_for(score),
        reasons=sorted(reasons, key=lambda r: -r["points"]),
        evidence={"developer": dev, "developer_id": dev_id, "installs": item.get("installs"),
                  "rating": item.get("rating"), "permissions": item.get("permissions", []),
                  "description": desc[:400], "image_path": item.get("_image_path", ""),
                  "logo": {"verdict": lg.verdict, "similarity": lg.similarity}},
        url=item.get("url", ""),
    )
