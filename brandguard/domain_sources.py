"""Look-alike / fraudulent DOMAIN discovery (no API keys needed).

1. Generate likely fake domains from the brand name (typos, glyph swaps, scam words, TLD swaps)
   and check which of them exist in DNS.
2. Search public Certificate Transparency logs (crt.sh) for domains containing the brand name.
   This also finds fakes we would never have guessed, plus when their certificate was first issued.
3. For the domains found, fetch the public HTML page (never executes scripts) to look for scam
   wording and password / OTP forms. Private / internal IP addresses are never fetched.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from datetime import datetime, timezone

from .detect import _reg_domain
from .profile import BrandProfile, norm_domain
from .social_sources import _age_days, _http_get, _parallel, _strip_html
from .sources import Source, SourceResult
from .textmatch import generate_variants, lookalike

TLDS = ["com", "in", "net", "org", "co", "io", "xyz", "online", "site", "top", "info",
        "app", "shop", "support", "help", "live", "club", "co.in"]
SCAM_WORDS = ["support", "login", "secure", "official", "verify", "pay", "rewards", "kyc",
              "help", "care", "app", "refund", "customercare", "update"]
LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def candidate_domains(brand: BrandProfile, limit: int = 300) -> list[str]:
    official = {norm_domain(d) for d in brand.domains}
    flat = re.sub(r"[^a-z0-9]", "", brand.name.lower())
    hyph = re.sub(r"[^a-z0-9]+", "-", brand.name.lower()).strip("-")
    labels = [flat, hyph]
    for w in SCAM_WORDS:
        labels += [f"{flat}{w}", f"{flat}-{w}", f"{w}{flat}", f"{w}-{flat}"]
    for v in generate_variants(brand.name, 60):
        v = re.sub(r"[^a-z0-9-]", "", v.replace(" ", "-").replace("_", "-").lower())
        labels.append(v)
    for a in brand.aliases:
        a = re.sub(r"[^a-z0-9]", "", a.lower())
        if len(a) >= 5:
            labels += [a, f"{a}-support", f"{a}-login"]
    out, seen = [], set()
    for lab in labels:
        if not LABEL_RE.match(lab):
            continue
        for tld in TLDS:
            d = f"{lab}.{tld}"
            if d not in seen and d not in official:
                seen.add(d)
                out.append(d)
    # plain brand name on every TLD first (TLD squatting), then the rest
    out.sort(key=lambda d: (d.split(".")[0] not in (flat, hyph), ))
    return out[:limit]


def _resolve(domain: str):
    """Returns list of IPs, [] if the name does not exist. Raises on resolver trouble."""
    try:
        return sorted({ai[4][0] for ai in socket.getaddrinfo(domain, None, proto=socket.IPPROTO_TCP)})
    except socket.gaierror as e:
        if e.errno in (socket.EAI_NONAME, getattr(socket, "EAI_NODATA", -5)):
            return []
        raise


def _public(ips: list[str]) -> bool:
    try:
        return bool(ips) and all(ipaddress.ip_address(i).is_global for i in ips)
    except ValueError:
        return False


def _crt_domains(flat: str) -> dict[str, str]:
    """registered domain -> earliest certificate date, from Certificate Transparency (crt.sh)."""
    r = _http_get("https://crt.sh/", params={"q": f"%{flat}%", "output": "json"}, timeout=25)
    r.raise_for_status()
    found: dict[str, str] = {}
    for row in r.json():
        when = (row.get("not_before") or "")[:19]
        for name in (row.get("name_value") or "").split("\n"):
            name = name.strip().lower().lstrip("*.")
            if flat in re.sub(r"[^a-z0-9]", "", name):
                reg = _reg_domain(name)
                if reg and (reg not in found or (when and when < found[reg])):
                    found[reg] = when
    return found


def _page(domain: str, ips: list[str]) -> dict:
    """Fetch the public landing page (HTML only). Never touches non-public IPs."""
    if not _public(ips):
        return {}
    for scheme in ("https", "http"):
        try:
            r = _http_get(f"{scheme}://{domain}/", timeout=6, allow_redirects=True)
        except Exception:
            continue
        if r.status_code >= 400:
            continue
        raw = (r.text or "")[:200_000]
        title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
        body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
        return {"title": _strip_html(title.group(1))[:200] if title else "",
                "page_text": re.sub(r"\s+", " ", _strip_html(body))[:3000],
                "has_login": bool(re.search(r'type=["\']?password|name=["\']?otp|\botp\b', raw, re.I)),
                "page_url": f"{scheme}://{domain}/"}
    return {}


class DomainScanSource(Source):
    name, kind = "Look-alike domains (DNS + Certificate Transparency)", "domain"

    def __init__(self, max_candidates: int = 300, max_pages: int = 30, use_crt: bool = True):
        self.max_candidates, self.max_pages, self.use_crt = max_candidates, max_pages, use_crt

    def fetch(self, brand: BrandProfile) -> SourceResult:
        flat = re.sub(r"[^a-z0-9]", "", brand.name.lower())
        official = {norm_domain(d) for d in brand.domains}
        cands = candidate_domains(brand, self.max_candidates)
        notes, first_seen, sources = [], {}, {}

        if self.use_crt:
            try:
                for reg, when in _crt_domains(flat).items():
                    if reg not in official and not any(reg.endswith("." + o) for o in official):
                        first_seen[reg] = when
                        sources.setdefault(reg, set()).add("certificate")
            except Exception as e:
                notes.append(f"crt.sh unavailable ({type(e).__name__})")

        res, errs = _parallel(lambda d: (d, _resolve(d)), cands, workers=20)
        ips_by = {d: ips for d, ips in res}
        for d, ips in res:
            if ips:
                sources.setdefault(d, set()).add("dns")
        if not res and errs:
            return SourceResult(self.name, self.kind, "unavailable",
                                message=f"DNS lookups failed ({errs[0]}).")
        # certificate-only domains: resolve them too
        extra = [d for d in first_seen if d not in ips_by]
        res2, _ = _parallel(lambda d: (d, _resolve(d)), extra, workers=20)
        ips_by.update(dict(res2))

        domains = [d for d in sources if d not in official]
        live = [d for d in domains if ips_by.get(d)][: self.max_pages]
        page_res, _ = _parallel(lambda d: (d, _page(d, ips_by.get(d, []))), live, workers=8)
        pages = dict(page_res)

        items = []
        for d in domains:
            age = _age_days(first_seen[d]) if first_seen.get(d) else None
            it = {"domain": d, "name": d.split(".")[0], "sources": sorted(sources[d]), "ips": ips_by.get(d, []),
                  "live": bool(ips_by.get(d)), "first_seen_days": age, "title": "", "page_text": "",
                  "has_login": False, "url": f"https://{d}"}
            it.update(pages.get(d, {}))
            items.append(it)
        msg = f"{len(cands)} look-alike names checked, {len(items)} registered"
        if notes:
            msg += " (" + "; ".join(notes) + ")"
        if errs:
            msg += f" ({len(errs)} DNS lookups failed)"
        return SourceResult(self.name, self.kind, "ok", items, msg)
