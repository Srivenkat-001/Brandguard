"""Live brand-details checklist, create/edit flow support (rename) and the app smoke test."""
from pathlib import Path

from brandguard import ui
from brandguard.profile import BrandProfile, OfficialAccount
from brandguard.storage import Store

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "data/demo"


def states(b):
    return {i["key"]: i["state"] for i in b.checklist()}


def test_empty_profile_needs_everything():
    b = BrandProfile(name="")
    assert set(states(b).values()) == {"missing"} and b.completeness() == 0


def test_demo_brand_is_complete():
    b = BrandProfile.load(DEMO / "brand.json")
    assert set(states(b).values()) == {"ok"} and b.completeness() == 100


def test_checklist_updates_as_details_are_added():
    b = BrandProfile(name="Acme")
    assert states(b)["name"] == "ok" and states(b)["domains"] == "missing"
    before = b.completeness()
    b.domains = ["acme.com"]
    b.official_accounts = [OfficialAccount("x", "acme")]
    assert states(b)["domains"] == "ok" and states(b)["accounts"] == "ok" and b.completeness() > before


def test_invalid_values_are_flagged_not_counted():
    b = BrandProfile(name="Acme", domains=["not a domain"], logo_path="missing.png",
                     official_accounts=[OfficialAccount("myspace", "acme")])
    s = states(b)
    assert s["domains"] == "invalid" and s["logo"] == "invalid" and s["accounts"] == "invalid"


def test_levels_and_panel_markup():
    items = BrandProfile(name="Acme").checklist()
    assert {i["key"] for i in items if i["level"] == "required"} == {"name", "domains", "logo"}
    out = ui.checklist_panel(items, 12)
    assert "\n" not in out and "12%" in out and "required detail(s) still needed" in out
    hostile = BrandProfile(name="<script>x</script>", keywords=["<img src=x onerror=1>"])
    assert "<script" not in ui.checklist_panel(hostile.checklist(), 0) and "<img" not in ui.checklist_panel(hostile.checklist(), 0)


def test_rename_brand_moves_everything():
    st = Store(":memory:")
    b = BrandProfile.load(DEMO / "brand.json")
    st.save_brand(b)
    st.log_run(b.name, {"scanned": 1}, [])
    st.rename_brand(b.name, "Veridian Group")
    assert st.list_brands() == ["Veridian Group"] and st.last_run("Veridian Group") and not st.last_run(b.name)


def test_app_has_create_and_edit_buttons(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not at.exception
    labels = [b.label for b in at.button]
    assert any("Create brand" in l for l in labels) and any("Edit brand" in l for l in labels)
