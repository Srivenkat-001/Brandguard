"""Brand Guard - Digital Risk Protection (Social & App Monitoring).

    streamlit run app.py
"""
from pathlib import Path

import pandas as pd
import streamlit as st

from brandguard.engine import run_scan
from brandguard.profile import (PLATFORMS, STORES, BrandProfile, OfficialAccount, OfficialApp,
                                OfficialDeveloper)
from brandguard.sources import demo_sources, live_sources
from brandguard.storage import Store
from brandguard.textmatch import generate_variants, lookalike

ROOT = Path(__file__).resolve().parent
DEMO = ROOT / "data" / "demo"
UPLOADS = ROOT / "data" / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)
LEVEL_BADGE = {"high": ":red[HIGH]", "medium": ":orange[MEDIUM]", "low": ":blue[LOW]"}

st.set_page_config(page_title="Brand Guard", page_icon="🛡️", layout="wide")

# Streamlit Cloud: API keys live in the app's "Secrets" (Settings > Secrets), not in a .env file.
import os
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
st.title("🛡️ Brand Guard")
st.caption("Social & app impersonation monitoring: define what is legitimate, then find what is not.")

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Brand")
    brands = store.list_brands()
    if st.button("Load demo brand (Veridian Bank)", width="stretch"):
        demo = BrandProfile.load(DEMO / "brand.json")
        store.save_brand(demo)
        st.session_state["brand_name"] = demo.name
        st.rerun()
    if brands:
        idx = brands.index(st.session_state["brand_name"]) if st.session_state.get("brand_name") in brands else 0
        st.session_state["brand_name"] = st.selectbox("Active brand", brands, index=idx)
    else:
        st.info("No brand yet. Load the demo brand, or create one in the Brand Profile tab.")
    st.divider()
    st.caption("Everything is stored locally in brandguard.db")

brand = store.load_brand(st.session_state["brand_name"]) if st.session_state.get("brand_name") else None
tab_profile, tab_scan, tab_found, tab_lab = st.tabs(
    ["1. Brand Profile", "2. Scan", "3. Detections", "Look-alike lab"])

# ------------------------------------------------------------- brand profile
with tab_profile:
    st.subheader("Define your legitimate assets")
    st.write("Anything listed here is **never flagged**, and is the reference every detection is compared against.")
    b = brand or BrandProfile(name="")
    c1, c2 = st.columns(2)
    name = c1.text_input("Company / brand name *", b.name)
    domains = c2.text_input("Official domains (comma separated)", ", ".join(b.domains))
    aliases = c1.text_input("Aliases / short names", ", ".join(b.aliases))
    keywords = c2.text_input("Brand keywords (products, services)", ", ".join(b.keywords))
    description = st.text_area("Official description (used to spot copied app listings)", b.description, height=90)

    lc1, lc2 = st.columns([1, 2])
    up = lc1.file_uploader("Official logo (PNG/JPG)", type=["png", "jpg", "jpeg"])
    logo_path = b.logo_path
    if up is not None:
        safe = "".join(ch for ch in (name or "brand") if ch.isalnum()) or "brand"
        dest = UPLOADS / f"{safe}_logo.png"
        dest.write_bytes(up.getvalue())
        logo_path = str(dest)
    shown = (Path(logo_path) if Path(logo_path).is_absolute() else Path(b.base_dir) / logo_path) if logo_path else None
    if shown and shown.exists():
        lc2.image(str(shown), width=110, caption="Current official logo")

    st.markdown("**Official social accounts**")
    acc_df = st.data_editor(
        pd.DataFrame([{"platform": a.platform, "handle": a.handle} for a in b.official_accounts]
                     or [{"platform": "x", "handle": ""}]),
        num_rows="dynamic", width="stretch", key="acc",
        column_config={"platform": st.column_config.SelectboxColumn(options=PLATFORMS, required=True)})
    st.markdown("**Official mobile apps**")
    app_df = st.data_editor(
        pd.DataFrame([{"store": a.store, "app_id": a.app_id, "name": a.name} for a in b.official_apps]
                     or [{"store": "google_play", "app_id": "", "name": ""}]),
        num_rows="dynamic", width="stretch", key="apps",
        column_config={"store": st.column_config.SelectboxColumn(options=STORES, required=True)})
    st.markdown("**Official developers / publishers** (store developer *ids* are trusted; names alone are not)")
    dev_df = st.data_editor(
        pd.DataFrame([{"name": d.name, "developer_id": d.developer_id} for d in b.official_developers]
                     or [{"name": "", "developer_id": ""}]),
        num_rows="dynamic", width="stretch", key="devs")

    def collect() -> BrandProfile:
        split = lambda s: [x.strip() for x in s.split(",") if x.strip()]
        return BrandProfile.from_dict({
            "name": name.strip(), "domains": split(domains), "description": description,
            "logo_path": logo_path, "aliases": split(aliases), "keywords": split(keywords),
            "official_accounts": [r for r in acc_df.fillna("").to_dict("records") if r["handle"].strip()],
            "official_apps": [r for r in app_df.fillna("").to_dict("records") if r["app_id"].strip()],
            "official_developers": [r for r in dev_df.fillna("").to_dict("records")
                                    if r["name"].strip() or r["developer_id"].strip()],
            "allowlist": b.allowlist}, base_dir=b.base_dir)

    cand = collect()
    issues = cand.validate()
    for sev, msg in issues:
        (st.error if sev == "error" else st.warning)(msg)
    if not issues:
        st.success("Profile looks complete.")
    if st.button("Save brand profile", type="primary", disabled=cand.has_errors()):
        store.save_brand(cand)
        st.session_state["brand_name"] = cand.name
        st.success(f"Saved '{cand.name}'.")
        st.rerun()

# ---------------------------------------------------------------------- scan
with tab_scan:
    st.subheader("Scan external sources")
    if not brand:
        st.info("Create or load a brand first.")
    else:
        mode = st.radio("Sources", ["Demo feeds (offline, always works)", "Live: app stores + social media (needs internet)"],
                        horizontal=True)
        st.caption("Live social: Bluesky, Mastodon, Reddit and handle-probing for Telegram / TikTok / Instagram / "
                   "Facebook work without keys. YouTube needs YOUTUBE_API_KEY and X needs X_BEARER_TOKEN. "
                   "Platforms that block lookups show as 'unavailable' and the scan continues.")
        if st.button("Run scan", type="primary"):
            sources = demo_sources(DEMO, domains=True) if mode.startswith("Demo") else live_sources()
            with st.spinner("Scanning..."):
                store.clear_detections(brand.name)
                run_scan(brand, sources, store)
            st.success("Scan complete. Open the Detections tab.")
        run = store.last_run(brand.name)
        if run:
            s = run["summary"]
            m = st.columns(6)
            for col, (label, key) in zip(m, [("Scanned", "scanned"), ("Official (skipped)", "excluded_official"),
                                             ("Allow-listed", "excluded_allowlisted"), ("No brand link", "no_identity_signal"),
                                             ("Below threshold", "below_threshold"), ("Flagged", "flagged")]):
                col.metric(label, s.get(key, 0))
            st.markdown("**Source status**")
            for src in run["sources"]:
                ok = src["status"] == "ok"
                st.markdown(f"{'🟢' if ok else '🟠'} **{src['source']}**: "
                            f"{src['records']} records, {src['message']}" + ("" if ok else " *(skipped, scan continued)*"))

# ---------------------------------------------------------------- detections
with tab_found:
    if not brand:
        st.info("Create or load a brand first.")
    else:
        dets = store.detections(brand.name)
        if not dets:
            st.info("No detections yet. Run a scan.")
        f1, f2, f3 = st.columns(3)
        kind = f1.selectbox("Type", ["all", "social", "app", "domain"])
        level = f2.selectbox("Risk", ["all", "high", "medium", "low"])
        status = f3.selectbox("Status", ["open (new)", "confirmed", "dismissed", "all"])
        for d in dets:
            if kind != "all" and d["kind"] != kind: continue
            if level != "all" and d["level"] != level: continue
            if status.startswith("open") and d["status"] != "new": continue
            if status in ("confirmed", "dismissed") and d["status"] != status: continue
            icon = {"social": "👤", "app": "📱", "domain": "🌐"}[d["kind"]]
            with st.expander(f"{icon} {d['title']}  ·  {d['platform']}  ·  score {d['score']}  ·  "
                             f"{d['level'].upper()}  ·  {d['status']}"):
                left, right = st.columns([1, 4])
                img = d["evidence"].get("image_path")
                if img and Path(img).exists():
                    left.image(img, width=96, caption="candidate")
                official_logo = brand.logo_file()
                if official_logo:
                    left.image(str(official_logo), width=96, caption="official")
                right.markdown(f"**Why it was flagged** ({LEVEL_BADGE[d['level']]} risk)")
                for r in d["reasons"]:
                    right.markdown(f"- **+{r['points']}** {r['detail']}")
                ev = d["evidence"]
                if d["kind"] == "social":
                    right.caption(f"Bio: {ev.get('bio','')}  |  followers: {ev.get('followers')}  |  "
                                  f"age: {ev.get('account_age_days')} days")
                elif d["kind"] == "domain":
                    right.caption(f"Found via: {', '.join(ev.get('sources', []))}  |  "
                                  f"certificate age: {ev.get('first_seen_days')} days  |  "
                                  f"login form: {ev.get('has_login')}  |  IPs: {', '.join(ev.get('ips', [])[:2])}")
                    if ev.get("title"):
                        right.caption(f"Page title: {ev['title']}")
                else:
                    right.caption(f"Publisher: {ev.get('developer')} ({ev.get('developer_id')})  |  "
                                  f"installs: {ev.get('installs')}  |  rating: {ev.get('rating')}")
                if d["url"]:
                    right.markdown(f"[Open source page]({d['url']})")
                b1, b2, b3, _ = right.columns([1, 1, 1.4, 3])
                if b1.button("Confirm", key=f"c{d['id']}"):
                    store.set_status(d["id"], "confirmed"); st.rerun()
                if b2.button("Dismiss", key=f"d{d['id']}"):
                    store.set_status(d["id"], "dismissed"); st.rerun()
                if b3.button("Mark as legitimate", key=f"l{d['id']}", help="Adds to the allowlist; never flagged again"):
                    brand.allowlist.append(f"{d['kind']}:{d['platform']}:{d['ref']}")
                    store.save_brand(brand); store.set_status(d["id"], "dismissed"); st.rerun()

# ------------------------------------------------------------ look-alike lab
with tab_lab:
    st.subheader("Look-alike name checker")
    if not brand:
        st.info("Create or load a brand first.")
    else:
        probe = st.text_input("Try a name or handle", "Veridian_Bank_Support")
        if probe:
            r = lookalike(probe, brand.match_names())
            if r.hit:
                st.error(f"Look-alike ({r.score:.0%}): {r.describe()}")
            elif r.score > 0:
                st.warning(f"Weak match ({r.score:.0%}): {r.describe()}. Not reported on its own.")
            else:
                st.success("Not a look-alike. Normal, unrelated names are not flagged.")
        st.markdown("**Variants used to seed live store searches**")
        st.code(", ".join(generate_variants(brand.name, 25)))
