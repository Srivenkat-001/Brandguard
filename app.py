"""Brand Guard - Digital Risk Protection (Social & App Monitoring).

    streamlit run app.py

Colour language: GREEN = original / legitimate, YELLOW = low risk, ORANGE = medium risk, RED = high risk.
"""
import os
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from brandguard import ui
from brandguard.engine import rescan
from brandguard.profile import PLATFORMS, STORES, BrandProfile
from brandguard.sources import demo_sources, live_sources
from brandguard.storage import Store
from brandguard.textmatch import generate_variants, lookalike

ROOT = Path(__file__).resolve().parent
DEMO = ROOT / "data" / "demo"
UPLOADS = ROOT / "data" / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)

DEMO_MODE = "Demo data (offline, always works)"
LIVE_MODE = "Live: app stores + social media (needs internet)"
THREAT_PAGE, ORIGINAL_PAGE = 15, 8

st.set_page_config(page_title="Brand Guard", page_icon="🛡️", layout="wide", initial_sidebar_state="expanded")
st.markdown(ui.CSS, unsafe_allow_html=True)

# Streamlit Cloud: API keys live in the app's "Secrets" (Settings > Secrets), not in a .env file.
try:
    for _k in ("YOUTUBE_API_KEYS", "YOUTUBE_API_KEY", "X_BEARER_TOKENS", "X_BEARER_TOKEN",
               "IG_ACCOUNTS", "IG_ACCOUNT", "IG_GRAPH_VERSION"):
        if _k in st.secrets and _k not in os.environ:
            os.environ[_k] = str(st.secrets[_k])
except Exception:      # no secrets configured (local run): fine
    pass


@st.cache_resource
def get_store() -> Store:
    return Store(ROOT / "brandguard.db")


store = get_store()


# --------------------------------------------------------------- callbacks
# Callbacks run before the page re-renders, so the screen already shows the new state.
def flash(msg: str) -> None:
    st.session_state["flash"] = msg


def cb_load_demo() -> None:
    demo = BrandProfile.load(DEMO / "brand.json")
    store.save_brand(demo)
    st.session_state["brand_name"] = demo.name
    flash("Demo brand loaded. Press Run scan.")


def cb_status(det_id: int, status: str, msg: str) -> None:
    store.set_status(det_id, status)
    flash(msg)


def _allow_key(kind: str, platform: str, ref: str) -> str:
    return f"{kind}:{platform}:{ref}"


def cb_legit(brand_name: str, d: dict) -> None:
    """Analyst says this is legitimate: allowlist it so it is never flagged again, and show it in green."""
    b = store.load_brand(brand_name)
    key = _allow_key(d["kind"], d["platform"], d["ref"])
    if key.lower() not in {a.lower() for a in b.allowlist}:
        b.allowlist.append(key)
        store.save_brand(b)
    store.set_status(d["id"], "dismissed")
    store.add_verified(brand_name, {
        "kind": d["kind"], "source": d["source"], "platform": d["platform"], "ref": d["ref"],
        "title": d["title"], "url": d["url"], "via": "allowlist", "detail": "Approved by your team (allowlist)",
        "evidence": {"image_path": d["evidence"].get("image_path", "")}})
    flash("Moved to Original (green). It will not be flagged again.")


def cb_unapprove(brand_name: str, v: dict) -> None:
    b = store.load_brand(brand_name)
    key = _allow_key(v["kind"], v["platform"], v["ref"]).lower()
    b.allowlist = [a for a in b.allowlist if a.lower() != key]
    store.save_brand(b)
    store.remove_verified(brand_name, v["kind"], v["platform"], v["ref"])
    flash("Approval removed. Run a scan to check it again.")


def cb_more(which: str, base: int, step: int) -> None:
    st.session_state[which] = st.session_state.get(which, base) + step


def cb_example(text: str) -> None:
    st.session_state["probe"] = text


# ------------------------------------------------------- create / edit dialog
@st.dialog("Brand profile", width="large")
def brand_editor(mode: str) -> None:
    """Create a new brand or edit the active one. The checklist on the right re-checks on every change."""
    editing = mode == "edit"
    old = store.load_brand(st.session_state.get("brand_name", "")) if editing else None
    b = old or BrandProfile(name="")
    suffix = f"{mode}_{b.name or 'new'}"           # per-brand widget keys: editing one brand never leaks into another
    st.markdown(f"##### {'✏️ Edit ' + b.name if editing else '➕ Create a new brand'}")
    st.caption("Anything listed here is **never flagged**, and is the reference every detection is compared against.")
    form, side = st.columns([1.75, 1], gap="medium")
    with form:
        c1, c2 = st.columns(2)
        name = c1.text_input("Company / brand name *", b.name, key=f"name_{suffix}")
        domains = c2.text_input("Official domains (comma separated)", ", ".join(b.domains), key=f"dom_{suffix}")
        aliases = c1.text_input("Aliases / short names", ", ".join(b.aliases), key=f"ali_{suffix}")
        keywords = c2.text_input("Brand keywords (products, services)", ", ".join(b.keywords), key=f"kw_{suffix}")
        description = st.text_area("Official description (used to spot copied app listings)", b.description,
                                   height=90, key=f"desc_{suffix}")
        up = st.file_uploader("Official logo (PNG/JPG)", type=["png", "jpg", "jpeg"], key=f"logo_{suffix}")
        logo_path = b.logo_path
        if up is not None:
            safe = "".join(ch for ch in (name or "brand") if ch.isalnum()) or "brand"
            dest = UPLOADS / f"{safe}_logo.png"
            dest.write_bytes(up.getvalue())
            logo_path = str(dest)
        shown = (Path(logo_path) if Path(logo_path).is_absolute() else Path(b.base_dir) / logo_path) if logo_path else None
        if shown and shown.exists():
            st.image(str(shown), width=90, caption="Current official logo")

        st.markdown("**Official social accounts**")
        acc_df = st.data_editor(
            pd.DataFrame([{"platform": x.platform, "handle": x.handle} for x in b.official_accounts]
                         or [{"platform": "x", "handle": ""}]),
            num_rows="dynamic", width="stretch", key=f"acc_{suffix}",
            column_config={"platform": st.column_config.SelectboxColumn(options=PLATFORMS, required=True)})
        st.markdown("**Official mobile apps**")
        app_df = st.data_editor(
            pd.DataFrame([{"store": x.store, "app_id": x.app_id, "name": x.name} for x in b.official_apps]
                         or [{"store": "google_play", "app_id": "", "name": ""}]),
            num_rows="dynamic", width="stretch", key=f"apps_{suffix}",
            column_config={"store": st.column_config.SelectboxColumn(options=STORES, required=True)})
        st.markdown("**Official developers / publishers** (store developer *ids* are trusted; names alone are not)")
        dev_df = st.data_editor(
            pd.DataFrame([{"name": x.name, "developer_id": x.developer_id} for x in b.official_developers]
                         or [{"name": "", "developer_id": ""}]),
            num_rows="dynamic", width="stretch", key=f"devs_{suffix}")

    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]
    cand = BrandProfile.from_dict({
        "name": name.strip(), "domains": split(domains), "description": description,
        "logo_path": logo_path, "aliases": split(aliases), "keywords": split(keywords),
        "official_accounts": [r for r in acc_df.fillna("").to_dict("records") if r["handle"].strip()],
        "official_apps": [r for r in app_df.fillna("").to_dict("records") if r["app_id"].strip()],
        "official_developers": [r for r in dev_df.fillna("").to_dict("records")
                                if r["name"].strip() or r["developer_id"].strip()],
        "allowlist": b.allowlist}, base_dir=b.base_dir)

    others = [n for n in store.list_brands() if n != (old.name if old else None)]
    clash = bool(cand.name) and cand.name.lower() in {n.lower() for n in others}
    with side:
        st.html(ui.checklist_panel(cand.checklist(), cand.completeness()))
    for sev, text in cand.validate():
        if sev == "error":
            st.error(text)
    if clash:
        st.error(f"A brand called '{cand.name}' already exists. Pick another name, or edit that brand instead.")
    s1, s2 = st.columns([1, 1])
    if s1.button("Save brand profile" if editing else "Create brand", type="primary", width="stretch",
                 disabled=cand.has_errors() or clash, key=f"save_{suffix}"):
        if old and old.name != cand.name:
            store.rename_brand(old.name, cand.name)
        store.save_brand(cand)
        st.session_state["brand_name"] = cand.name
        flash(f"Saved '{cand.name}'." if editing else f"Created '{cand.name}'. Press Run scan.")
        st.rerun()
    if s2.button("Cancel", width="stretch", key=f"cancel_{suffix}"):
        st.rerun()


def brand_buttons(where: str, has_brand: bool) -> None:
    """The Create / Edit buttons, shown in the sidebar and on the Brand profile tab."""
    b1, b2 = st.columns(2)
    if b1.button("➕ Create brand", key=f"create_{where}", width="stretch", type="primary" if not has_brand else "secondary",
                 help="Start a new brand profile"):
        brand_editor("create")
    if b2.button("✏️ Edit brand", key=f"edit_{where}", width="stretch", disabled=not has_brand,
                 help="Change the active brand's profile" if has_brand else "Create or load a brand first"):
        brand_editor("edit")


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("#### Brand")
    brands = store.list_brands()
    if brands:
        idx = brands.index(st.session_state["brand_name"]) if st.session_state.get("brand_name") in brands else 0
        st.session_state["brand_name"] = st.selectbox("Active brand", brands, index=idx)
    else:
        st.info("No brand yet. Create one, or load the demo brand.")
    brand_buttons("sidebar", bool(brands))
    st.button("Load demo brand (Veridian Bank)", width="stretch", on_click=cb_load_demo)
    st.divider()
    st.markdown("#### Colour guide")
    st.html(ui.legend())
    st.caption("Every card also carries a text label, so colour is never the only signal.")
    st.divider()
    st.caption("Everything is stored locally in brandguard.db")

brand = store.load_brand(st.session_state["brand_name"]) if st.session_state.get("brand_name") else None
official_logo = ui.thumb(brand.logo_file()) if brand else ""

st.html(ui.hero(brand.name if brand else None, ui.thumb(brand.logo_file(), 52) if brand else ""))
if msg := st.session_state.pop("flash", None):
    st.toast(msg, icon="✅")

tab_dash, tab_profile, tab_lab = st.tabs(["🛡️ Dashboard", "🏷️ Brand profile", "🧪 Look-alike lab"])


# --------------------------------------------------------------- card views
def render_threat(d: dict) -> None:
    with st.container(key=ui.card_class(d["level"], d["id"])):
        st.html(ui.threat_card(d, official_logo))
        c1, c2, c3, _ = st.columns([1.25, 1.1, 1.6, 3])
        slots = []
        if d["status"] != "confirmed":
            slots.append(("confirm", "✔ Confirm threat", "primary", "This is a real impersonation",
                          (d["id"], "confirmed", "Marked as a confirmed threat.")))
        if d["status"] != "dismissed":
            slots.append(("dismiss", "Dismiss", "secondary", "Not a threat for now: hide it",
                          (d["id"], "dismissed", "Dismissed. Set Status to Dismissed to see it again.")))
        if d["status"] != "new":
            slots.append(("reopen", "↺ Reopen", "secondary", "Move it back to New",
                          (d["id"], "new", "Moved back to New.")))
        for col, (name, label, kind, tip, args) in zip((c1, c2), slots[:2]):
            col.button(label, key=f"{name}{d['id']}", type=kind, help=tip, width="stretch",
                       on_click=cb_status, args=args)
        c3.button("Mark as legitimate", key=f"legit{d['id']}", width="stretch",
                  help="It is really yours: it moves to Original and is never flagged again",
                  on_click=cb_legit, args=(brand.name, d))


def render_original(v: dict) -> None:
    with st.container(key=ui.card_class("original", f"v{v['id']}")):
        st.html(ui.original_card(v))
        if v["via"] == "allowlist":
            st.button("Remove approval", key=f"unapprove{v['id']}", help="Treat it as a normal candidate again",
                      on_click=cb_unapprove, args=(brand.name, v))


# ---------------------------------------------------------------- dashboard
with tab_dash:
    if not brand:
        st.html(ui.empty_state(
            "🛡️", "Welcome to Brand Guard",
            "Tell it what is genuinely yours, and it finds everything that pretends to be you.",
            [("Define your brand", "List your official accounts, apps and websites."),
             ("Run a scan", "It checks social media, app stores and look-alike domains."),
             ("Review the colours", "Green is original. Yellow, orange and red are threats by risk.")]))
        st.button("Load the demo brand to try it", type="primary", key="empty_demo", on_click=cb_load_demo)
    else:
        with st.container(key="bgtool"):
            t1, t2 = st.columns([3, 1.1], vertical_alignment="center")
            mode = t1.radio("Scan source", [DEMO_MODE, LIVE_MODE], horizontal=True, label_visibility="collapsed",
                            help="Live needs internet. Platforms that block lookups show as 'unavailable' "
                                 "and the scan carries on. YouTube needs YOUTUBE_API_KEY and X needs X_BEARER_TOKEN.")
            run_clicked = t2.button("🔎 Run scan", type="primary", width="stretch")
        if run_clicked:
            srcs = demo_sources(DEMO, domains=True) if mode == DEMO_MODE else live_sources()
            with st.spinner("Scanning sources…"):
                rescan(brand, srcs, store)
            for k in ("limit_t", "limit_o"):
                st.session_state.pop(k, None)
            flash("Scan complete. Your earlier confirm / dismiss decisions were kept.")
            st.rerun()

        run = store.last_run(brand.name)
        dets, verified = store.detections(brand.name), store.verified(brand.name)
        counts = ui.summarize(dets, verified)

        if run:
            s = run["summary"]
            down = sum(1 for x in run["sources"] if x["status"] != "ok")
            st.caption(f"Last scan {time.strftime('%d %b %Y, %H:%M', time.localtime(run['started']))}  ·  "
                       f"{s.get('scanned', 0)} items checked" + (f"  ·  {down} source(s) unavailable" if down else ""))
        st.html(ui.status_banner(counts, scanned=bool(run)))
        if run:
            st.html(ui.distribution(counts) + ui.tiles(counts))
            with st.expander("Scan details: what was checked and which sources answered"):
                st.html(ui.funnel(run["summary"]) + ui.sources(run["sources"]))
        else:
            st.html("<div style='height:12px'></div>" + ui.empty_state(
                "🔎", "No scan yet", "Press Run scan above. The demo feeds work offline and take a few seconds."))

        if run:
            # ------------------------------------------------------ filters
            def view_label(k: str) -> str:
                return {"all": f"All · {counts['active'] + counts['original']}",
                        "high": f"🔴 High · {counts['high']}", "medium": f"🟠 Medium · {counts['medium']}",
                        "low": f"🟡 Low · {counts['low']}", "original": f"🟢 Original · {counts['original']}"}[k]

            st.write("")
            f1, f2, f3 = st.columns([3.2, 1.2, 1.2])
            view = f1.segmented_control("Show", ["all", "high", "medium", "low", "original"], default="all",
                                        format_func=view_label, key="f_view", label_visibility="collapsed") or "all"
            kind = f2.selectbox("Type", ["all", "social", "app", "domain"], key="f_kind", label_visibility="collapsed",
                                format_func={"all": "All types", "social": "👤 Social", "app": "📱 Apps",
                                             "domain": "🌐 Websites"}.get)
            status = f3.selectbox("Status", ["active", "confirmed", "dismissed", "all"], key="f_status",
                                  label_visibility="collapsed",
                                  format_func={"active": "Active (new + confirmed)", "confirmed": "Confirmed only",
                                               "dismissed": "Dismissed", "all": "All statuses"}.get)

            threats = [d for d in dets
                       if (kind == "all" or d["kind"] == kind)
                       and (view in ("all", d["level"]))
                       and (status == "all" or (status == "active" and d["status"] != "dismissed")
                            or d["status"] == status)] if view != "original" else []
            originals = [v for v in verified if kind == "all" or v["kind"] == kind] if view in ("all", "original") else []

            if not threats and not originals:
                st.html(ui.empty_state("🙂", "Nothing matches these filters",
                                       "Change the Show, Type or Status filter above to see more."))

            # ------------------------------------------------------ threats
            if threats:
                st.html(ui.section("Threats", len(threats), "neutral", "most dangerous first"))
                lim = st.session_state.get("limit_t", THREAT_PAGE)
                for d in threats[:lim]:
                    render_threat(d)
                if len(threats) > lim:
                    st.button(f"Show {min(THREAT_PAGE, len(threats) - lim)} more threats ({len(threats) - lim} hidden)",
                              key="more_t", on_click=cb_more, args=("limit_t", THREAT_PAGE, THREAT_PAGE))

            # ------------------------------------------------------ originals
            if originals:
                st.html(ui.section("Original", len(originals), "original", "your verified assets, never flagged"))
                lim = st.session_state.get("limit_o", ORIGINAL_PAGE)
                for v in originals[:lim]:
                    render_original(v)
                if len(originals) > lim:
                    st.button(f"Show all {len(originals) - lim} more originals", key="more_o",
                              on_click=cb_more, args=("limit_o", ORIGINAL_PAGE, len(originals)))

# ------------------------------------------------------------ brand profile
with tab_profile:
    brand_buttons("tab", bool(brand))
    if brand:
        left, right = st.columns([1.35, 1], gap="medium")
        left.html(ui.assets_panel(brand, official_logo))
        right.html(ui.checklist_panel(brand.checklist(), brand.completeness()))
    else:
        st.html(ui.empty_state("🏷️", "No brand profile yet",
                               "Create one to tell Brand Guard what is genuinely yours.",
                               [("Press Create brand", "Enter the name, domains and logo."),
                                ("Add official assets", "Accounts, apps and publisher ids are never flagged."),
                                ("Watch the checklist", "It shows what is still needed, as you type.")]))

# ---------------------------------------------------------- look-alike lab
with tab_lab:
    if not brand:
        st.html(ui.empty_state("🧪", "Create or load a brand first",
                               "The look-alike checker compares any name against your brand."))
    else:
        st.markdown("##### Is this name a look-alike of your brand?")
        st.session_state.setdefault("probe", f"{brand.name.replace(' ', '_')}_Support")
        probe = st.text_input("Try a name or handle", key="probe")
        examples = list(dict.fromkeys([f"{brand.name} Support", f"{brand.name.split()[0]} Bakery",
                                       *generate_variants(brand.name, 4)]))[:5]
        st.caption("Quick examples")
        for col, ex in zip(st.columns(len(examples)), examples):
            col.button(ex, key=f"ex_{ex}", on_click=cb_example, args=(ex,), width="stretch")
        if probe:
            r = lookalike(probe, brand.match_names())
            if r.hit:
                st.html(ui.lab_result("high", "Look-alike detected", r.describe(), f"{r.score:.0%}"))
            elif r.score > 0:
                st.html(ui.lab_result("low", "Weak match", f"{r.describe()}. Not reported on its own.", f"{r.score:.0%}"))
            else:
                st.html(ui.lab_result("original", "Not a look-alike",
                                      "Normal, unrelated names are not flagged."))
        with st.expander("Variants used to seed live store searches"):
            st.code(", ".join(generate_variants(brand.name, 25)))
