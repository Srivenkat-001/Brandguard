"""Evidence report (PDF) to send to a platform / app store / registrar when reporting an impersonator.

    build_report(brand, detections) -> bytes

One page-set per finding: who is being impersonated, what the offending account / app / site is, why it was
flagged (every signal with its points), the observed evidence (profile text, links, publisher, permissions,
logo comparison), the request, and a declaration block to sign. Pure functions, no Streamlit import.

Fonts: the built-in PDF fonts only cover Latin text, so any other character (a Cyrillic look-alike letter, an
emoji) is written as <U+XXXX>. That is also better evidence: the reader sees exactly which hidden letter was used.
"""
from __future__ import annotations

import io
import re
import time
import unicodedata
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .ui import KIND, SIGNAL, _facts, humanize_days, lookalike_chars, platform_name

INK, MUTED, LINE, BLUE = colors.HexColor("#1B2233"), colors.HexColor("#667085"), colors.HexColor("#D0D5DD"), colors.HexColor("#3B5BDB")
LEVEL_COLOR = {"high": colors.HexColor("#E5383B"), "medium": colors.HexColor("#F28C1B"), "low": colors.HexColor("#C99A00")}
LEVEL_WORD = {"high": "HIGH RISK", "medium": "MEDIUM RISK", "low": "LOW RISK"}
KIND_WORD = {"social": "social media account / page", "app": "mobile app", "domain": "website / domain"}
WIDTH = A4[0] - 36 * mm


# ------------------------------------------------------------------ helpers
def clean(text) -> str:
    """Make text safe for the built-in fonts and for reportlab's XML-ish paragraphs."""
    out = []
    for ch in " ".join(str(text if text is not None else "").split()):
        o = ord(ch)
        if ch in "&<>":
            out.append({"&": "&amp;", "<": "&lt;", ">": "&gt;"}[ch])
        elif 32 <= o < 127 or 0xA0 <= o <= 0xFF:
            out.append(ch)
        else:
            out.append(f"&lt;U+{o:04X}&gt;")
    return "".join(out)


def when(ts) -> str:
    return time.strftime("%d %b %Y, %H:%M UTC", time.gmtime(ts)) if ts else "unknown"


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    mk = lambda name, **kw: ParagraphStyle(name, parent=base, fontName=kw.pop("fontName", "Helvetica"), **kw)
    return {
        "body": mk("body", fontSize=9.5, leading=13, textColor=INK, alignment=TA_LEFT),
        "small": mk("small", fontSize=8, leading=10.5, textColor=MUTED),
        "cell": mk("cell", fontSize=8.8, leading=11.5, textColor=INK),
        "cellb": mk("cellb", fontSize=8.8, leading=11.5, textColor=INK, fontName="Helvetica-Bold"),
        "h1": mk("h1", fontSize=19, leading=23, textColor=INK, fontName="Helvetica-Bold", spaceAfter=2),
        "h2": mk("h2", fontSize=11.5, leading=15, textColor=BLUE, fontName="Helvetica-Bold", spaceBefore=11, spaceAfter=4),
        "mono": mk("mono", fontSize=8.5, leading=11, textColor=INK, fontName="Courier"),
    }


def _kv(rows: list[tuple[str, str]], st, label_w: float = 38 * mm, mono_keys: tuple = ()) -> Table:
    data = [[Paragraph(clean(k), st["cellb"]), Paragraph(clean(v) or "-", st["mono"] if k in mono_keys else st["cell"])]
            for k, v in rows]
    t = Table(data, colWidths=[label_w, WIDTH - label_w])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
                           ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F6F7FB")),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                           ("BOX", (0, 0), (-1, -1), 0.4, LINE)]))
    return t


def _resolve(path: str, *bases: str | Path) -> Path | None:
    if not path:
        return None
    p = Path(path)
    for cand in ([p] if p.is_absolute() else [Path(b) / p for b in bases if b] + [p]):
        if cand.exists():
            return cand
    return None


def _image(path: Path | None, box: float = 34 * mm):
    if not path:
        return None
    try:
        from PIL import Image as PILImage
        with PILImage.open(path) as im:
            w, h = im.size
        scale = min(box / w, box / h)
        # re-encode as PNG so odd formats / palettes always render
        buf = io.BytesIO()
        with PILImage.open(path) as im:
            im.convert("RGBA").save(buf, "PNG")
        buf.seek(0)
        return Image(buf, width=w * scale, height=h * scale)
    except Exception:
        return None


def _footer(case: str):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm, f"Brand Guard impersonation report  |  {case}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()
    return draw


# ----------------------------------------------------------------- sections
def _header(brand, d: dict, case: str, st) -> list:
    lv = d["level"] if d["level"] in LEVEL_COLOR else "low"
    chip = Table([[Paragraph(f'<font color="white"><b>{LEVEL_WORD[lv]}  |  SCORE {int(d["score"])}/100</b></font>', st["cell"])]],
                 colWidths=[62 * mm])
    chip.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LEVEL_COLOR[lv]), ("TOPPADDING", (0, 0), (-1, -1), 4),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    chip.hAlign = "LEFT"
    kind = KIND_WORD.get(d["kind"], d["kind"])
    return [Paragraph("Impersonation report", st["h1"]),
            Paragraph(clean(f"Report against a fake {kind} impersonating {brand.name}"), st["body"]), Spacer(1, 6), chip,
            Spacer(1, 6),
            _kv([("Case reference", case), ("Report date", when(time.time())),
                 ("Reporting brand", brand.name), ("Review status", {"new": "Detected, awaiting review",
                                                                 "confirmed": "Confirmed by analyst",
                                                                 "dismissed": "Dismissed by analyst"}.get(d["status"], d["status"]))],
                st)]


def _offender(d: dict, st) -> list:
    ev = d["evidence"]
    rows = [("Type", KIND_WORD.get(d["kind"], d["kind"])),
            ("Platform", "Website" if d["platform"] == "web" else platform_name(d["platform"])),
            ("Name shown", d["title"]),
            ("Handle / app id / domain", d["ref"])]
    if d.get("url"):
        rows.append(("Address (URL)", d["url"]))
    rows += [("First detected", when(d.get("first_seen"))), ("Last seen", when(d.get("last_seen")))]
    odd = lookalike_chars(d["title"]) + lookalike_chars(d["ref"])
    if odd:
        rows.append(("Hidden look-alike letters", ", ".join(dict.fromkeys(odd)) + ": letters from another alphabet "
                     "that look like Latin letters, used to copy the name."))
    return [Paragraph("1. The reported account", st["h2"]), _kv(rows, st, mono_keys=("Handle / app id / domain", "Address (URL)"))]


def _official(brand, d: dict, st) -> list:
    rows = [("Brand", brand.name)]
    if brand.domains:
        rows.append(("Official websites", ", ".join(brand.domains)))
    if d["kind"] == "social":
        same = [f"@{a.handle}" for a in brand.official_accounts if a.platform == d["platform"]]
        rows.append((f"Official {platform_name(d['platform'])} account(s)", ", ".join(same) or "none registered on this platform"))
    elif d["kind"] == "app":
        rows.append(("Official app(s)", ", ".join(f"{a.name or a.app_id} ({a.app_id})" for a in brand.official_apps) or "-"))
        rows.append(("Official publisher(s)", ", ".join(f"{x.name} (id {x.developer_id or 'n/a'})"
                                                         for x in brand.official_developers) or "-"))
    return [Paragraph("2. The genuine brand (for comparison)", st["h2"]), _kv(rows, st)]


def _signals(d: dict, st) -> list:
    rows = [[Paragraph("Signal", st["cellb"]), Paragraph("Pts", st["cellb"]), Paragraph("What was found", st["cellb"])]]
    for r in d["reasons"]:
        if r.get("points", 0) > 0:
            rows.append([Paragraph(clean(SIGNAL.get(r["signal"], r["signal"])), st["cell"]),
                         Paragraph(f"+{int(r['points'])}", st["cell"]), Paragraph(clean(r["detail"]), st["cell"])])
    t = Table(rows, colWidths=[34 * mm, 12 * mm, WIDTH - 46 * mm], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAEFFF")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("GRID", (0, 0), (-1, -1), 0.4, LINE), ("TOPPADDING", (0, 0), (-1, -1), 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return [Paragraph("3. Why it is an impersonation", st["h2"]),
            Paragraph("Each signal below was measured automatically and is listed with the points it added to the risk score.",
                      st["small"]), Spacer(1, 3), t]


def _observed(d: dict, st) -> list:
    ev = d["evidence"]
    rows = [(a, b) for a, b in _facts(d) if a not in ("Bio", "Page title", "Permissions")]
    if ev.get("bio"):
        rows.append(("Profile text (bio)", ev["bio"]))
    if ev.get("title"):
        rows.append(("Page title", ev["title"]))
    if ev.get("page_text"):
        rows.append(("Page text", ev["page_text"]))
    if ev.get("description"):
        rows.append(("App description", ev["description"][:600]))
    if ev.get("permissions"):
        rows.append(("Permissions requested", ", ".join(ev["permissions"])))
    for ln in (ev.get("links") or [])[:6]:
        rows.append((f"Link ({ln.get('type', 'link')})", ln.get("url", "")))
    return [Paragraph("4. Observed content", st["h2"]), _kv(rows, st, mono_keys=tuple(k for k, _ in rows if k.startswith("Link")))]


def _visual(brand, d: dict, root, st) -> list:
    off = _image(brand.logo_file())
    cand = _image(_resolve(d["evidence"].get("image_path", ""), root, brand.base_dir))
    if not (off and cand):
        return []
    sim = (d["evidence"].get("logo") or {}).get("similarity")
    cap = f"Reported {'icon' if d['kind'] == 'app' else 'profile image'}" + (f" ({sim:.0%} similar)" if isinstance(sim, (int, float)) and sim else "")
    t = Table([[off, cand], [Paragraph("Official logo", st["small"]), Paragraph(clean(cap), st["small"])]],
              colWidths=[(WIDTH / 2)] * 2)
    t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("BOX", (0, 0), (-1, -1), 0.4, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return [KeepTogether([Paragraph("5. Visual comparison", st["h2"]), t])]


def _request(brand, d: dict, st) -> list:
    kind = KIND_WORD.get(d["kind"], d["kind"])
    what = {"social": "remove or suspend the account / page and block re-registration of the same name",
            "app": "remove the app from the store, suspend the publisher account and block re-submission",
            "domain": "suspend or take down the domain and its web content"}.get(d["kind"], "remove the content")
    txt = (f"{clean(brand.name)} requests that you {what}. The reported {kind} copies the brand's name and branding "
           f"without authorisation and is likely to mislead and defraud customers. It is not operated by, or affiliated with, "
           f"{clean(brand.name)}.")
    checklist = ["Screenshot of the profile / store page / website, with the date visible",
                 "The exact URL (listed above) and the handle, app id or domain",
                 "Proof of ownership of the genuine brand: trademark certificate, official website or verified account",
                 "Any victim reports or messages received, if available"]
    sign = Table([[Paragraph("Name", st["cell"]), "", Paragraph("Title", st["cell"]), ""],
                  [Paragraph("Email", st["cell"]), "", Paragraph("Phone", st["cell"]), ""],
                  [Paragraph("Signature", st["cell"]), "", Paragraph("Date", st["cell"]), ""]],
                 colWidths=[20 * mm, WIDTH / 2 - 20 * mm, 18 * mm, WIDTH / 2 - 18 * mm], rowHeights=[9 * mm] * 3)
    sign.setStyle(TableStyle([("LINEBELOW", (1, 0), (1, -1), 0.5, INK), ("LINEBELOW", (3, 0), (3, -1), 0.5, INK),
                              ("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
    return [KeepTogether([Paragraph("6. Request", st["h2"]), Paragraph(txt, st["body"]), Spacer(1, 4),
                          Paragraph("Attach with this report:", st["cellb"]),
                          *[Paragraph(f"- {clean(c)}", st["cell"]) for c in checklist]]),
            KeepTogether([Paragraph("7. Declaration", st["h2"]),
                          Paragraph(clean(f"I am authorised to act for {brand.name}. The information in this report is accurate to the best of "
                                          "my knowledge, and the reported item is not authorised by the brand owner."), st["body"]),
                          Spacer(1, 8), sign]),
            Spacer(1, 8),
            Paragraph("This report was produced by Brand Guard from automated checks of public data at the time shown. "
                      "Scores are transparent heuristics, not a legal finding. Review the evidence before you sign, and "
                      "attach your own screenshots because pages can change or be removed.", st["small"])]


def _summary(brand, dets: list[dict], st) -> list:
    rows = [[Paragraph(h, st["cellb"]) for h in ("#", "Risk", "Type", "Platform", "Name / handle")]]
    for i, d in enumerate(dets, 1):
        rows.append([Paragraph(str(i), st["cell"]), Paragraph(f"{LEVEL_WORD.get(d['level'], d['level'])} ({int(d['score'])})", st["cell"]),
                     Paragraph(clean(KIND_WORD.get(d["kind"], d["kind"]).split(" /")[0]), st["cell"]),
                     Paragraph(clean("Website" if d["platform"] == "web" else platform_name(d["platform"])), st["cell"]),
                     Paragraph(clean(f"{d['title']} ({d['ref']})"), st["cell"])])
    t = Table(rows, colWidths=[8 * mm, 32 * mm, 22 * mm, 26 * mm, WIDTH - 88 * mm], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAEFFF")), ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    n = {lv: sum(1 for d in dets if d["level"] == lv) for lv in LEVEL_WORD}
    return [Paragraph("Impersonation report: summary", st["h1"]),
            Paragraph(clean(f"{len(dets)} fake accounts, apps or sites impersonating {brand.name}: "
                            f"{n['high']} high, {n['medium']} medium, {n['low']} low risk. "
                            "A separate evidence page follows for each, ready to send to the platform."), st["body"]),
            Spacer(1, 8), t, PageBreak()]


# --------------------------------------------------------------------- main
def build_report(brand, dets: list[dict], root: str | Path = ".") -> bytes:
    """PDF bytes: a summary page (when there are several) then one evidence section per finding."""
    dets = sorted(dets, key=lambda d: -d["score"])
    st = _styles()
    day = time.strftime("%Y%m%d")
    slug = re.sub(r"[^A-Za-z0-9]+", "", brand.name)[:12].upper() or "BRAND"
    case = f"BG-{day}-{slug}-{dets[0]['id']}" if len(dets) == 1 else f"BG-{day}-{slug}-{len(dets)}ITEMS"
    story: list = []
    if len(dets) > 1:
        story += _summary(brand, dets, st)
    for i, d in enumerate(dets):
        d_case = f"BG-{day}-{slug}-{d['id']}"
        story += [*_header(brand, d, d_case, st), *_offender(d, st), *_official(brand, d, st), *_signals(d, st),
                  *_observed(d, st), *_visual(brand, d, root, st), *_request(brand, d, st)]
        if i < len(dets) - 1:
            story.append(PageBreak())
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                            title=f"Impersonation report: {brand.name}", author="Brand Guard")
    doc.build(story, onFirstPage=_footer(case), onLaterPages=_footer(case))
    return buf.getvalue()
