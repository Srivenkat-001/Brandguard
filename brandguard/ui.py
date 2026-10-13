"""Visual layer for the Streamlit app: one colour language, pure functions, no Streamlit import.

Colour language (never used for anything else, so it can be read at a glance):
    GREEN   original / legitimate  (your own verified assets, or ones an analyst approved)
    YELLOW  low risk      ORANGE  medium risk      RED  high risk
Every colour is paired with a text label and an icon, so it also works without colour vision.

Every builder returns a single-line HTML string (no blank lines, no indentation) so it renders
identically through st.html / st.markdown and in the static preview. All scraped text is escaped.
"""
from __future__ import annotations

import base64
import html
import io
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from .detect import LEVELS

LEVEL_ORDER = ["high", "medium", "low"]
META = {
    "high": {"label": "High risk", "short": "HIGH", "icon": "▲", "hint": "Act now",
             "advice": "Very likely an impersonation. Review it now, then confirm it and report it to the platform."},
    "medium": {"label": "Medium risk", "short": "MEDIUM", "icon": "◆", "hint": "Review soon",
               "advice": "Suspicious. Check the evidence below, then confirm or dismiss it."},
    "low": {"label": "Low risk", "short": "LOW", "icon": "●", "hint": "Keep an eye on it",
            "advice": "Weak signals only. Dismiss it if it is harmless, or watch it for changes."},
    "original": {"label": "Original", "short": "ORIGINAL", "icon": "✓", "hint": "Verified legitimate",
                 "advice": ""},
    "info": {"label": "Info", "short": "INFO", "icon": "i", "hint": "", "advice": ""},
}
PLATFORM = {"x": "X (Twitter)", "instagram": "Instagram", "facebook": "Facebook", "linkedin": "LinkedIn",
            "telegram": "Telegram", "youtube": "YouTube", "tiktok": "TikTok", "bluesky": "Bluesky",
            "mastodon": "Mastodon", "reddit": "Reddit", "google_play": "Google Play",
            "app_store": "App Store", "web": "Website"}
KIND = {"social": ("👤", "Social"), "app": ("📱", "App"), "domain": ("🌐", "Website")}
SIGNAL = {"name": "Look-alike name", "logo": "Copied logo", "icon": "Copied icon", "scam_text": "Scam wording",
          "brand_mention": "Uses your brand", "domain": "Look-alike link", "link": "Suspicious link",
          "account_age": "New account", "followers": "Few followers", "verified": "Not verified",
          "login_form": "Fake login form", "new_domain": "Brand-new site", "tld": "Risky ending",
          "publisher": "Wrong publisher", "publisher_name": "Copied publisher",
          "description_mention": "Names your brand", "description": "Copied description",
          "risky_text": "Risky wording", "permissions": "Risky permissions", "installs": "Few installs"}


# ----------------------------------------------------------------- helpers
def esc(x) -> str:
    """Escape untrusted text for HTML. Also flattens whitespace (newlines would end an HTML block in
    markdown) and neutralises '$' (Streamlit markdown would treat pairs of them as maths)."""
    s = html.escape("" if x is None else str(x), quote=True)
    return " ".join(s.split()).replace("$", "&#36;")


def safe_url(u: str) -> str:
    """Only plain http(s) links are ever rendered as links (never javascript:, data:, ...)."""
    try:
        p = urlparse(u or "")
    except ValueError:
        return ""
    return u if p.scheme in ("http", "https") and p.netloc else ""


def platform_name(p: str) -> str:
    return PLATFORM.get(p, (p or "").replace("_", " ").title())


def level_ranges() -> dict[str, str]:
    """e.g. {'high': '70–100', 'medium': '40–69', 'low': '25–39'} derived from the detection thresholds."""
    out, upper = {}, 100
    for cut, name in LEVELS:
        out[name] = f"{cut}–{upper}"
        upper = cut - 1
    return out


def lookalike_chars(text: str) -> list[str]:
    """Non-Latin letters hiding inside Latin text (e.g. Cyrillic 'е' in 'Veridian'): a classic spoofing trick."""
    import unicodedata
    text = text or ""
    if not any(c.isascii() and c.isalpha() for c in text):
        return []
    out = []
    for c in dict.fromkeys(text):
        if not c.isascii() and c.isalpha():
            name = unicodedata.name(c, "")
            out.append(f"'{c}' ({name.split()[0].title() if name else 'non-Latin'})")
    return out


def humanize_days(n) -> str:
    if n is None:
        return "unknown"
    n = int(n)
    if n < 60:
        return f"{n} days"
    if n < 730:
        return f"{round(n / 30)} months"
    return f"{n / 365:.1f} years"


@lru_cache(maxsize=256)
def _thumb(path: str, mtime: int, size: int) -> str:
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGBA")
        im.thumbnail((size, size))
        buf = io.BytesIO()
        im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def thumb(path, size: int = 96) -> str:
    """Small data-URI version of a local image ('' if missing/unreadable); safe to embed in HTML."""
    if not path:
        return ""
    try:
        p = Path(path)
        return _thumb(str(p), p.stat().st_mtime_ns, size) if p.exists() else ""
    except Exception:
        return ""


def summarize(dets: list[dict], verified: list[dict]) -> dict:
    """Counts for the dashboard. Dismissed findings no longer count as active threats."""
    c = {"high": 0, "medium": 0, "low": 0, "original": len(verified), "dismissed": 0, "confirmed": 0}
    for d in dets:
        if d["status"] == "dismissed":
            c["dismissed"] += 1
            continue
        c[d["level"]] = c.get(d["level"], 0) + 1
        if d["status"] == "confirmed":
            c["confirmed"] += 1
    c["active"] = c["high"] + c["medium"] + c["low"]
    return c


def card_class(level: str, ident) -> str:
    """Streamlit container key. Streamlit turns it into the CSS class `st-key-<key>` that the CSS targets."""
    return f"bgcard-{level}-{ident}"


# -------------------------------------------------------------------- CSS
CSS = """<style>
:root{--bg-ink:#1B2233;--bg-text:#344054;--bg-muted:#667085;--bg-line:#E4E7EC;--bg-blue:#3B5BDB;
--bg-green:#1E9E5A;--bg-green-ink:#0F6B3B;--bg-green-soft:#E8F7EE;--bg-green-line:#A9DEC0;
--bg-yellow:#F2C200;--bg-yellow-ink:#7A5B00;--bg-yellow-soft:#FFF6D1;--bg-yellow-line:#F6DC7A;
--bg-orange:#F28C1B;--bg-orange-ink:#8A4B00;--bg-orange-soft:#FFEBD5;--bg-orange-line:#F8C894;
--bg-red:#E5383B;--bg-red-ink:#9B1C1F;--bg-red-soft:#FDE5E5;--bg-red-line:#F5AFB0}
.bg-lv-high{--c:var(--bg-red);--ink:var(--bg-red-ink);--soft:var(--bg-red-soft);--line:var(--bg-red-line)}
.bg-lv-medium{--c:var(--bg-orange);--ink:var(--bg-orange-ink);--soft:var(--bg-orange-soft);--line:var(--bg-orange-line)}
.bg-lv-low{--c:var(--bg-yellow);--ink:var(--bg-yellow-ink);--soft:var(--bg-yellow-soft);--line:var(--bg-yellow-line)}
.bg-lv-original{--c:var(--bg-green);--ink:var(--bg-green-ink);--soft:var(--bg-green-soft);--line:var(--bg-green-line)}
.bg-lv-info{--c:var(--bg-blue);--ink:#243B9B;--soft:#EAEFFF;--line:#C5D0FA}
.bg-lv-neutral{--c:#98A2B3;--ink:#475467;--soft:#F2F4F7;--line:#E4E7EC}
[class*="st-key-bgcard-high"]{--c:var(--bg-red)}[class*="st-key-bgcard-medium"]{--c:var(--bg-orange)}
[class*="st-key-bgcard-low"]{--c:var(--bg-yellow)}[class*="st-key-bgcard-original"]{--c:var(--bg-green)}

.block-container{padding-top:3.2rem;max-width:1180px;margin-left:auto;margin-right:auto}
footer{visibility:hidden}
button[data-baseweb="tab"]{font-weight:650;font-size:1rem}
[data-testid="stButton"] button,.stButton>button{border-radius:10px;font-weight:600}

div[class*="st-key-bgcard-"]{background:#fff;border:1px solid var(--bg-line);border-left:6px solid var(--c);
border-radius:14px;padding:16px 18px 12px;box-shadow:0 1px 2px rgba(16,24,40,.05);gap:.55rem;transition:box-shadow .15s}
div[class*="st-key-bgcard-"]:hover{box-shadow:0 6px 18px rgba(16,24,40,.09)}
div.st-key-bgtool{background:#fff;border:1px solid var(--bg-line);border-radius:14px;padding:12px 16px}

.bg-hero{display:flex;align-items:center;gap:14px;margin:0 0 .9rem;font-family:inherit}
.bg-logo{width:46px;height:46px;border-radius:13px;background:linear-gradient(135deg,#3B5BDB,#6C8CFF);display:grid;
place-items:center;color:#fff;font-size:23px;box-shadow:0 6px 16px rgba(59,91,219,.30);flex:none}
.bg-hero .t{font-size:1.55rem;font-weight:780;line-height:1.1;color:var(--bg-ink);letter-spacing:-.01em}
.bg-hero .s{color:var(--bg-muted);font-size:.93rem;margin-top:3px}
.bg-brandpill{margin-left:auto;display:flex;align-items:center;gap:8px;background:#fff;border:1px solid var(--bg-line);
border-radius:99px;padding:6px 14px 6px 8px;font-weight:650;color:var(--bg-ink);font-size:.9rem}
.bg-brandpill img{width:26px;height:26px;border-radius:50%;object-fit:cover}

.bg-banner{display:flex;gap:14px;align-items:center;padding:16px 18px;border-radius:14px;background:var(--soft);
border:1px solid var(--line);color:var(--ink);font-family:inherit}
.bg-banner .ic{width:42px;height:42px;border-radius:50%;background:var(--c);color:#fff;display:grid;place-items:center;
font-weight:800;font-size:18px;flex:none}
.bg-banner b{display:block;font-size:1.1rem;line-height:1.25}.bg-banner span{font-size:.92rem;opacity:.92}
.bg-dist{display:flex;height:10px;border-radius:99px;overflow:hidden;background:#E9ECF2;margin:14px 0 2px;gap:2px}
.bg-dist i{display:block;height:100%}
.bg-tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:12px 0 4px;font-family:inherit}
.bg-tile{background:#fff;border:1px solid var(--bg-line);border-radius:14px;padding:14px 16px 12px 20px;position:relative;overflow:hidden}
.bg-tile:before{content:"";position:absolute;left:0;top:0;bottom:0;width:6px;background:var(--c)}
.bg-tile .n{font-size:2rem;font-weight:780;line-height:1;color:var(--ink)}
.bg-tile .l{margin-top:7px;font-size:.86rem;font-weight:700;color:var(--bg-ink)}
.bg-tile .h{font-size:.76rem;color:var(--bg-muted);margin-top:1px}
.bg-tiles.mini{grid-template-columns:repeat(6,1fr);gap:10px}
.bg-tiles.mini .bg-tile{padding:10px 12px 9px 16px}.bg-tiles.mini .n{font-size:1.5rem}.bg-tiles.mini .l{font-size:.8rem;margin-top:4px}
.bg-sec{display:flex;align-items:center;gap:10px;margin:22px 0 8px;font-family:inherit;font-weight:750;font-size:1.05rem;color:var(--bg-ink)}
.bg-sec .cnt{font-size:.78rem;font-weight:700;padding:2px 10px;border-radius:99px;background:var(--soft);color:var(--ink);border:1px solid var(--line)}
.bg-sec .sub{font-weight:500;color:var(--bg-muted);font-size:.86rem}

.bg-cardin{font-family:inherit;color:var(--bg-text)}
.bg-row{display:flex;gap:14px;align-items:flex-start}
.bg-ring{--p:50;width:56px;height:56px;border-radius:50%;flex:none;position:relative;display:grid;place-items:center;
background:conic-gradient(var(--c) calc(var(--p)*1%),#E9ECF2 0)}
.bg-ring:after{content:"";position:absolute;inset:6px;background:#fff;border-radius:50%}
.bg-ring b{position:relative;z-index:1;font-size:1.08rem;color:var(--ink);font-weight:800}
.bg-ring.ok{background:var(--c)}.bg-ring.ok:after{display:none}.bg-ring.ok b{color:#fff;font-size:1.5rem}
.bg-main{flex:1;min-width:0}
.bg-title{font-weight:720;font-size:1.04rem;color:var(--bg-ink);overflow-wrap:anywhere;line-height:1.3}
.bg-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.bg-tag{font-size:.74rem;font-weight:600;padding:2px 9px;border-radius:99px;background:#F2F4F7;color:#475467;border:1px solid #E4E7EC}
.bg-tag.sig{background:var(--soft);color:var(--ink);border-color:var(--line)}
.bg-tag.status{background:#fff;color:#475467}
.bg-tag.status.confirmed{background:var(--bg-red-soft);color:var(--bg-red-ink);border-color:var(--bg-red-line)}
.bg-sum{margin-top:8px;font-size:.92rem}
.bg-pill{flex:none;font-size:.73rem;font-weight:800;letter-spacing:.07em;padding:5px 12px;border-radius:99px;
background:var(--soft);color:var(--ink);border:1px solid var(--line);white-space:nowrap}
.bg-row.mid{align-items:center}.bg-ring.sm{width:38px;height:38px}.bg-ring.sm b{font-size:1.15rem}
.bg-note{font-size:.84rem;color:var(--bg-muted);align-self:center;margin-left:4px}.bg-facts .wide{flex-basis:100%}
div[class*="st-key-bgcard-original"]{padding:10px 16px}
.bg-more{margin-top:10px;border-top:1px dashed var(--bg-line);padding-top:9px}
.bg-more summary{cursor:pointer;font-weight:680;font-size:.88rem;color:var(--bg-blue);list-style:none}
.bg-more summary::-webkit-details-marker{display:none}
.bg-more summary:before{content:"▸  "}.bg-more[open] summary:before{content:"▾  "}
.bg-advice{margin:10px 0 0;padding:10px 12px;border-radius:10px;background:var(--soft);color:var(--ink);font-size:.9rem;font-weight:600}
.bg-why{list-style:none;margin:12px 0 0;padding:0;display:grid;gap:8px}
.bg-why li{display:flex;gap:10px;align-items:baseline;font-size:.9rem;color:var(--bg-text);margin:0;padding:0}
.bg-pts{flex:none;min-width:2.7rem;text-align:center;font-weight:800;font-size:.78rem;padding:2px 6px;border-radius:8px;
background:var(--soft);color:var(--ink);border:1px solid var(--line)}
.bg-facts{display:flex;flex-wrap:wrap;gap:6px 22px;margin-top:14px;font-size:.84rem;color:var(--bg-muted)}
.bg-facts b{color:var(--bg-ink);font-weight:650}
.bg-logos{display:flex;gap:16px;margin-top:14px}
.bg-lbox{text-align:center;font-size:.72rem;color:var(--bg-muted);font-weight:600}
.bg-lbox img{width:68px;height:68px;border-radius:12px;object-fit:contain;background:#fff;display:block;margin-bottom:4px;border:2px solid var(--bg-line)}
.bg-lbox.off img{border-color:var(--bg-green)}.bg-lbox.cand img{border-color:var(--c)}
.bg-link{display:inline-block;margin-top:12px;font-size:.84rem;font-weight:650;color:var(--bg-blue);text-decoration:none}

.bg-panel{background:#fff;border:1px solid var(--bg-line);border-radius:14px;padding:16px 18px;font-family:inherit;color:var(--bg-text)}
.bg-panel.ok{border-left:6px solid var(--bg-green)}
.bg-panel h4{margin:0 0 4px;font-size:1.05rem;color:var(--bg-ink);font-weight:750;padding:0}
.bg-panel p{margin:0 0 10px;color:var(--bg-muted);font-size:.9rem}
.bg-group{margin-top:12px}.bg-group .gl{font-size:.74rem;font-weight:750;letter-spacing:.06em;text-transform:uppercase;color:var(--bg-muted);margin-bottom:6px}
.bg-chips{display:flex;flex-wrap:wrap;gap:8px}
.bg-chip{display:inline-flex;align-items:center;gap:6px;padding:5px 12px;border-radius:99px;background:var(--bg-green-soft);
color:var(--bg-green-ink);border:1px solid var(--bg-green-line);font-size:.85rem;font-weight:620}
.bg-chip:before{content:"✓";font-weight:800}.bg-chip small{font-weight:500;opacity:.8}
.bg-profile{display:flex;gap:16px;align-items:flex-start}
.bg-profile img{width:76px;height:76px;border-radius:16px;border:2px solid var(--bg-green);object-fit:contain;background:#fff;flex:none}

.bg-src{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px;font-family:inherit}
.bg-srcchip{display:inline-flex;align-items:center;gap:8px;padding:6px 12px;border:1px solid var(--bg-line);border-radius:10px;
background:#fff;font-size:.84rem;color:var(--bg-text)}
.bg-dot{width:9px;height:9px;border-radius:50%;background:var(--bg-green);flex:none}.bg-dot.off{background:#98A2B3}
.bg-srcchip small{color:var(--bg-muted)}

.bg-empty{text-align:center;padding:34px 22px;background:#fff;border:1px dashed #CBD2DC;border-radius:16px;font-family:inherit}
.bg-empty .big{font-size:2.2rem}.bg-empty h3{margin:6px 0 4px;color:var(--bg-ink);font-size:1.25rem;font-weight:760;padding:0}
.bg-empty p{margin:0 auto;color:var(--bg-muted);max-width:560px;font-size:.95rem}
.bg-steps{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:20px;text-align:left}
.bg-step{background:#F8F9FC;border:1px solid var(--bg-line);border-radius:12px;padding:12px 14px;font-size:.88rem;color:var(--bg-text)}
.bg-step b{display:block;color:var(--bg-ink);margin-bottom:2px}
.bg-step .no{display:inline-grid;place-items:center;width:22px;height:22px;border-radius:50%;background:var(--bg-blue);color:#fff;
font-size:.78rem;font-weight:800;margin-right:6px}

.bg-legend{font-family:inherit;display:grid;gap:8px;font-size:.86rem;color:var(--bg-text)}
.bg-legend div{display:flex;align-items:center;gap:9px}
.bg-legend i{width:12px;height:12px;border-radius:4px;background:var(--c);flex:none}
.bg-legend small{color:var(--bg-muted);margin-left:auto}
.bg-lab{font-family:inherit}.bg-lab .sc{margin-left:auto;font-size:1.6rem;font-weight:800;color:var(--ink)}

.bg-fakebtn{display:inline-block;padding:7px 14px;border:1px solid #D0D5DD;border-radius:10px;font-weight:600;font-size:.9rem;
margin-right:8px;background:#fff;color:#1B2233}.bg-fakebtn.pri{background:#3B5BDB;border-color:#3B5BDB;color:#fff}

.bg-check{font-family:inherit;background:#fff;border:1px solid var(--bg-line);border-radius:14px;padding:14px 16px}
.bg-check .top{display:flex;align-items:center;gap:12px;margin-bottom:8px}
.bg-check .top b{color:var(--bg-ink);font-size:1rem}.bg-check .top span{color:var(--bg-muted);font-size:.84rem}
.bg-check .pct{margin-left:auto;font-weight:800;font-size:1.4rem;color:var(--bg-blue)}
.bg-check .bar{height:8px;border-radius:99px;background:#EAEFFF;overflow:hidden;margin-bottom:10px}
.bg-check .bar i{display:block;height:100%;background:var(--bg-blue);border-radius:99px}
.bg-check .row{display:flex;gap:10px;align-items:flex-start;padding:7px 0;border-top:1px solid #F0F2F6;font-size:.9rem;color:var(--bg-text)}
.bg-check .row .st{flex:none;width:22px;height:22px;border-radius:99px;display:flex;align-items:center;justify-content:center;
font-weight:800;font-size:.8rem;background:#EAEFFF;color:#243B9B}
.bg-check .row.ok .st{background:var(--bg-blue);color:#fff}
.bg-check .row.invalid .st{background:#fff;color:#243B9B;border:2px solid var(--bg-blue)}
.bg-check .row b{color:var(--bg-ink);font-weight:680}
.bg-check .row small{display:block;color:var(--bg-muted);font-size:.8rem;margin-top:1px}
.bg-check .lvl{margin-left:auto;flex:none;font-size:.7rem;font-weight:750;letter-spacing:.04em;text-transform:uppercase;
color:#243B9B;background:#EAEFFF;border-radius:99px;padding:2px 8px}
.bg-check .row.req.missing .lvl,.bg-check .row.req.invalid .lvl{background:var(--bg-blue);color:#fff}

@media(max-width:760px){.bg-tiles,.bg-tiles.mini{grid-template-columns:repeat(2,1fr)}.bg-steps{grid-template-columns:1fr}
.bg-row{flex-wrap:wrap}.bg-brandpill{display:none}}
</style>"""


# -------------------------------------------------------- page-level pieces
def hero(brand_name: str | None = None, logo_uri: str = "") -> str:
    pill = ""
    if brand_name:
        img = f'<img src="{logo_uri}" alt="">' if logo_uri else "🛡️"
        pill = f'<div class="bg-brandpill">{img}<span>{esc(brand_name)}</span></div>'
    return ('<div class="bg-hero"><div class="bg-logo">🛡️</div><div><div class="t">Brand Guard</div>'
            '<div class="s">Find fake profiles, apps and websites that copy your brand, ranked by risk.</div></div>'
            f'{pill}</div>')


def banner(level: str, title: str, text: str = "") -> str:
    lv = level if level in META else "info"
    return (f'<div class="bg-banner bg-lv-{lv}"><div class="ic">{META[lv]["icon"]}</div>'
            f'<div><b>{esc(title)}</b><span>{esc(text)}</span></div></div>')


def status_banner(counts: dict, scanned: bool) -> str:
    """The one-sentence answer to 'am I OK?', coloured by the worst active threat."""
    if not scanned:
        return banner("info", "Ready to scan", "Press Run scan to look for fake profiles, apps and websites.")
    h, m, lo = counts["high"], counts["medium"], counts["low"]
    plural = lambda n, w: f"{n} {w}" + ("" if n == 1 else "s")
    if h:
        extra = f" and {plural(m + lo, 'other finding')}" if m + lo else ""
        return banner("high", f"{plural(h, 'high-risk threat')} need{'s' if h == 1 else ''} your attention{extra}",
                      "Start with the red cards below: they are the most likely impersonations.")
    if m:
        return banner("medium", f"{plural(m, 'medium-risk finding')} to review",
                      "Nothing critical, but these look suspicious. Check the evidence and confirm or dismiss.")
    if lo:
        return banner("low", f"{plural(lo, 'low-risk finding')} to keep an eye on",
                      "Only weak signals so far. Dismiss anything harmless.")
    if counts.get("dismissed"):
        return banner("original", "All clear: nothing left to review", "You have dismissed every finding.")
    return banner("original", "All clear: no impersonation found",
                  "Everything we found that uses your brand is on your official list.")


def distribution(counts: dict) -> str:
    parts = [(counts[k], f"var(--bg-{ {'high': 'red', 'medium': 'orange', 'low': 'yellow', 'original': 'green'}[k] })")
             for k in ("high", "medium", "low", "original") if counts.get(k)]
    if not parts:
        return ""
    return '<div class="bg-dist">' + "".join(f'<i style="flex:{n};background:{c}"></i>' for n, c in parts) + "</div>"


def tiles(counts: dict) -> str:
    rng = level_ranges()
    spec = [("high", counts["high"], "High risk", f"score {rng['high']}"),
            ("medium", counts["medium"], "Medium risk", f"score {rng['medium']}"),
            ("low", counts["low"], "Low risk", f"score {rng['low']}"),
            ("original", counts["original"], "Original", "your verified assets")]
    return '<div class="bg-tiles">' + "".join(
        f'<div class="bg-tile bg-lv-{lv}"><div class="n">{n}</div><div class="l">{label}</div><div class="h">{hint}</div></div>'
        for lv, n, label, hint in spec) + "</div>"


def section(title: str, count: int | None, level: str, sub: str = "") -> str:
    s = f'<span class="sub">{esc(sub)}</span>' if sub else ""
    c = f'<span class="cnt">{count}</span>' if count is not None else ""
    return f'<div class="bg-sec bg-lv-{level}">{esc(title)}{c}{s}</div>'


def funnel(summary: dict) -> str:
    spec = [("neutral", summary.get("scanned", 0), "Checked", "everything we looked at"),
            ("original", summary.get("excluded_official", 0), "Official", "yours, skipped"),
            ("original", summary.get("excluded_allowlisted", 0), "Approved", "marked legitimate"),
            ("neutral", summary.get("no_identity_signal", 0), "Unrelated", "no link to your brand"),
            ("neutral", summary.get("below_threshold", 0), "Too weak", "below the threshold"),
            ("high", summary.get("flagged", 0), "Flagged", "shown as threats")]
    return '<div class="bg-tiles mini">' + "".join(
        f'<div class="bg-tile bg-lv-{lv}"><div class="n">{n}</div><div class="l">{label}</div><div class="h">{hint}</div></div>'
        for lv, n, label, hint in spec) + "</div>"


def sources(items: list[dict]) -> str:
    chips = []
    for s in items:
        ok = s["status"] == "ok"
        msg = f'{s["records"]} records' if ok else f'unavailable: {s["message"]}'
        chips.append(f'<span class="bg-srcchip" title="{esc(s["message"])}"><span class="bg-dot{"" if ok else " off"}"></span>'
                     f'<b>{esc(s["source"])}</b><small>{esc(msg)[:90]}</small></span>')
    return '<div class="bg-src">' + "".join(chips) + "</div>"


def empty_state(icon: str, title: str, text: str, steps: list[tuple[str, str]] | None = None) -> str:
    st_html = ""
    if steps:
        st_html = '<div class="bg-steps">' + "".join(
            f'<div class="bg-step"><b><span class="no">{i}</span>{esc(t)}</b>{esc(d)}</div>'
            for i, (t, d) in enumerate(steps, 1)) + "</div>"
    return f'<div class="bg-empty"><div class="big">{icon}</div><h3>{esc(title)}</h3><p>{esc(text)}</p>{st_html}</div>'


def legend() -> str:
    rng = level_ranges()
    rows = [("original", "Original", "yours"), ("low", "Low risk", rng["low"]),
            ("medium", "Medium risk", rng["medium"]), ("high", "High risk", rng["high"])]
    return '<div class="bg-legend">' + "".join(
        f'<div class="bg-lv-{lv}"><i></i><span>{label}</span><small>{hint}</small></div>' for lv, label, hint in rows) + "</div>"


def lab_result(level: str, title: str, text: str, score: str = "") -> str:
    sc = f'<div class="sc">{esc(score)}</div>' if score else ""
    return (f'<div class="bg-banner bg-lab bg-lv-{level}"><div class="ic">{META[level]["icon"]}</div>'
            f'<div><b>{esc(title)}</b><span>{esc(text)}</span></div>{sc}</div>')


# ------------------------------------------------------------------- cards
def _signal_chips(reasons: list[dict], limit: int = 4) -> str:
    seen, labels = set(), []
    for r in reasons:
        lab = SIGNAL.get(r.get("signal"))
        if lab and lab not in seen and r.get("points", 0) > 0:
            seen.add(lab)
            labels.append(lab)
    chips = "".join(f'<span class="bg-tag sig">{esc(x)}</span>' for x in labels[:limit])
    if len(labels) > limit:
        chips += f'<span class="bg-tag">+{len(labels) - limit} more</span>'
    return chips


WIDE = {"Bio", "Page title", "Permissions", "Hidden look-alike letters"}


def _facts(d: dict) -> list[tuple[str, str]]:
    ev, k = d["evidence"], d["kind"]
    yes = lambda v: "Yes" if v else "No"
    if k == "social":
        f = [("Followers", f"{ev['followers']:,}" if isinstance(ev.get("followers"), int) else "unknown"),
             ("Account age", humanize_days(ev.get("account_age_days"))),
             ("Verified", yes(ev.get("verified")) if ev.get("verified") is not None else "unknown")]
        if ev.get("bio"):
            f.append(("Bio", ev["bio"][:160]))
        return f
    if k == "domain":
        f = [("Found via", ", ".join(ev.get("sources", [])) or "unknown"),
             ("Certificate age", humanize_days(ev.get("first_seen_days"))),
             ("Login form", yes(ev.get("has_login"))), ("Live", yes(ev.get("live", True)))]
        if ev.get("ips"):
            f.append(("Addresses", ", ".join(ev["ips"][:2])))
        if ev.get("title"):
            f.append(("Page title", ev["title"][:100]))
        return f
    f = [("Publisher", f"{ev.get('developer') or 'unknown'} ({ev.get('developer_id') or 'no id'})"),
         ("Installs", f"{ev['installs']:,}" if isinstance(ev.get("installs"), int) else "unknown"),
         ("Rating", str(ev.get("rating") if ev.get("rating") is not None else "unknown"))]
    if ev.get("permissions"):
        f.append(("Permissions", ", ".join(ev["permissions"][:5])))
    return f


def threat_card(d: dict, official_logo_uri: str = "") -> str:
    """Card body for a finding. The coloured left edge and white card come from the Streamlit container's CSS."""
    lv = d["level"] if d["level"] in LEVEL_ORDER else "low"
    icon, kind_name = KIND.get(d["kind"], ("", d["kind"]))
    status = {"new": "New", "confirmed": "Confirmed threat", "dismissed": "Dismissed"}.get(d["status"], d["status"])
    why = "".join(f'<li><span class="bg-pts">+{r["points"]}</span><span>{esc(r["detail"])}</span></li>'
                  for r in d["reasons"] if r.get("points", 0) > 0)
    odd = lookalike_chars(d["title"])
    fl = _facts(d) + ([("Hidden look-alike letters", ", ".join(odd))] if odd else [])
    facts = "".join(f'<span{" class=wide" if a in WIDE else ""}>{esc(a)}: <b>{esc(b)}</b></span>' for a, b in fl)
    odd_chip = '<span class="bg-tag sig">Mixed alphabets</span>' if odd else ""
    plat = "" if d["platform"] == "web" else f'<span class="bg-tag">{esc(platform_name(d["platform"]))}</span>'
    cand = thumb(d["evidence"].get("image_path"))
    logos = ""
    if cand and official_logo_uri:
        sim = (d["evidence"].get("logo") or {}).get("similarity")
        cap = f"candidate · {sim:.0%} similar" if isinstance(sim, (int, float)) and sim else "candidate"
        logos = (f'<div class="bg-logos"><div class="bg-lbox off"><img src="{official_logo_uri}" alt="official logo">official</div>'
                 f'<div class="bg-lbox cand"><img src="{cand}" alt="candidate image">{esc(cap)}</div></div>')
    link = safe_url(d.get("url", ""))
    link_html = (f'<a class="bg-link" href="{esc(link)}" target="_blank" rel="noopener noreferrer nofollow">'
                 'Open the suspicious page ↗ (be careful)</a>') if link else ""
    n_sig = len([r for r in d["reasons"] if r.get("points", 0) > 0])
    return (f'<div class="bg-cardin bg-lv-{lv}"><div class="bg-row">'
            f'<div class="bg-ring" style="--p:{max(4, min(100, int(d["score"])))}"><b>{int(d["score"])}</b></div>'
            f'<div class="bg-main"><div class="bg-title">{esc(d["title"])}</div>'
            f'<div class="bg-tags"><span class="bg-tag">{icon} {kind_name}</span>'
            f'{plat}<span class="bg-tag status {esc(d["status"])}">{esc(status)}</span></div>'
            f'<div class="bg-tags">{odd_chip}{_signal_chips(d["reasons"])}</div></div>'
            f'<div class="bg-pill">{META[lv]["icon"]} {META[lv]["short"]}</div></div>'
            f'<details class="bg-more"><summary>Why was this flagged? ({n_sig} signal{"" if n_sig == 1 else "s"}, score {int(d["score"])}/100)</summary>'
            f'<div class="bg-advice">{esc(META[lv]["advice"])}</div>'
            f'<ul class="bg-why">{why}</ul><div class="bg-facts">{facts}</div>{logos}{link_html}</details></div>')


def original_card(v: dict) -> str:
    approved = v.get("via") == "allowlist"
    icon, kind_name = KIND.get(v["kind"], ("", v["kind"]))
    plat = "" if v["platform"] == "web" else f'<span class="bg-tag">{esc(platform_name(v["platform"]))}</span>'
    cap = "Approved by your team" if approved else "Official"
    return (f'<div class="bg-cardin bg-lv-original"><div class="bg-row mid"><div class="bg-ring ok sm"><b>✓</b></div>'
            f'<div class="bg-main"><div class="bg-title">{esc(v["title"])}</div>'
            f'<div class="bg-tags"><span class="bg-tag">{icon} {kind_name}</span>{plat}'
            f'<span class="bg-tag sig">{cap}</span><span class="bg-note">{esc(v.get("detail", ""))}</span></div></div>'
            f'<div class="bg-pill">✓ {"APPROVED" if approved else "ORIGINAL"}</div></div></div>')


# ----------------------------------------------------------- brand profile
def assets_panel(brand, logo_uri: str = "") -> str:
    """Green summary of everything the profile protects (never flagged)."""
    def group(label, chips):
        return (f'<div class="bg-group"><div class="gl">{label}</div><div class="bg-chips">{"".join(chips)}</div></div>'
                if chips else "")
    chip = lambda main, small="": f'<span class="bg-chip">{esc(main)}{f" <small>{esc(small)}</small>" if small else ""}</span>'
    body = "".join([
        group("Websites", [chip(d) for d in brand.domains]),
        group("Social accounts", [chip(f"@{a.handle}", platform_name(a.platform)) for a in brand.official_accounts]),
        group("Mobile apps", [chip(a.name or a.app_id, platform_name(a.store)) for a in brand.official_apps]),
        group("Publishers", [chip(d.name or d.developer_id, d.developer_id) for d in brand.official_developers]),
        group("Approved by your team", [chip(a.split(":", 2)[-1], a.split(":", 1)[0]) for a in brand.allowlist]),
    ])
    if not body:
        body = '<p>Nothing listed yet. Add your official accounts, apps and domains below.</p>'
    img = f'<img src="{logo_uri}" alt="official logo">' if logo_uri else ""
    return (f'<div class="bg-panel ok"><div class="bg-profile">{img}<div style="flex:1">'
            f'<h4>✓ Protected as original: {esc(brand.name)}</h4>'
            '<p>Everything here is treated as legitimate and is never flagged.</p></div></div>'
            f'{body}</div>')


STATE_MARK = {"ok": "✓", "missing": "○", "invalid": "!"}
STATE_WORD = {"ok": "Done", "missing": "Needed", "invalid": "Fix this"}
LEVEL_WORD = {"required": "Required", "recommended": "Recommended", "optional": "Optional"}


def checklist_panel(items: list[dict], pct: int) -> str:
    """Live 'brand details needed' checklist. Blue only (green/yellow/orange/red stay reserved for risk);
    every row also has a text label and a symbol, so it never depends on colour."""
    rows = "".join(
        f'<div class="row {i["state"]}{" req" if i["level"] == "required" else ""}">'
        f'<div class="st" title="{STATE_WORD[i["state"]]}">{STATE_MARK[i["state"]]}</div>'
        f'<div><b>{esc(i["label"])}</b><small>{esc(i["detail"])}</small><small>Why: {esc(i["why"])}</small></div>'
        f'<span class="lvl">{LEVEL_WORD[i["level"]]}</span></div>' for i in items)
    need = sum(1 for i in items if i["level"] == "required" and i["state"] != "ok")
    sub = "All required details are in." if not need else f"{need} required detail(s) still needed."
    return (f'<div class="bg-check"><div class="top"><div><b>Brand details checklist</b><br><span>{sub}</span></div>'
            f'<div class="pct">{pct}%</div></div><div class="bar"><i style="width:{pct}%"></i></div>{rows}</div>')
