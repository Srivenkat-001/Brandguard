"""Command line:  python -m brandguard.cli scan [--brand PATH] [--live]"""
import argparse
from pathlib import Path

from .engine import run_scan
from .profile import BrandProfile
from .sources import demo_sources, live_sources
from .storage import Store

ROOT = Path(__file__).resolve().parent.parent
ICON = {"high": "HIGH  ", "medium": "MEDIUM", "low": "LOW   "}


def main():
    ap = argparse.ArgumentParser(prog="brandguard")
    ap.add_argument("cmd", choices=["scan"])
    ap.add_argument("--brand", default=str(ROOT / "data/demo/brand.json"))
    ap.add_argument("--live", action="store_true", help="use live app-store + social sources instead of demo feeds")
    ap.add_argument("--db", default=":memory:")
    a = ap.parse_args()

    brand = BrandProfile.load(a.brand)
    for sev, msg in brand.validate():
        print(f"[{sev}] {msg}")
    if brand.has_errors():
        raise SystemExit("Fix profile errors first.")
    sources = live_sources() if a.live else demo_sources(ROOT / "data/demo", domains=True)
    rep = run_scan(brand, sources, Store(a.db))

    print("\nSources")
    for s in rep.sources:
        print(f"  {'OK ' if s['status']=='ok' else '!! '} {s['source']:<28} {s['records']:>3} records  {s['message']}")
    print("\nSummary:", rep.summary, "\n")
    for d in rep.detections:
        print(f"{ICON[d.level]} {d.score:>3}  [{d.kind}/{d.platform}] {d.title}")
        for r in d.reasons[:4]:
            print(f"           +{r['points']:<3} {r['detail']}")
    
if __name__ == "__main__":
    main()
