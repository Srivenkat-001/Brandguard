"""Scan orchestration: sources -> exclusion -> detection -> storage."""
from __future__ import annotations

from dataclasses import dataclass, field

from .detect import (REPORT_THRESHOLD, Detection, brand_logo_hash, evaluate_app, evaluate_domain,
                     evaluate_social, exclusion_reason)
from .profile import BrandProfile
from .sources import Source
from .storage import Store


TEXT_FIELDS = ("name", "developer", "developer_id", "description", "display_name", "bio", "title", "page_text")


@dataclass
class ScanReport:
    detections: list[Detection] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    sources: list[dict] = field(default_factory=list)


def run_scan(brand: BrandProfile, sources: list[Source], store: Store | None = None,
             threshold: int = REPORT_THRESHOLD) -> ScanReport:
    b_hash = brand_logo_hash(brand)
    rep = ScanReport()
    counts = {"scanned": 0, "excluded_official": 0, "excluded_allowlisted": 0,
              "no_identity_signal": 0, "below_threshold": 0, "flagged": 0, "new": 0, "skipped_malformed": 0}
    for src in sources:
        res = src.safe_fetch(brand)
        rep.sources.append({"source": res.source, "kind": res.kind, "status": res.status,
                            "message": res.message, "records": len(res.items), "seconds": res.elapsed})
        id_key = {"social": "handle", "app": "app_id", "domain": "domain"}[res.kind]
        for item in res.items:
            if not item.get(id_key):          # malformed record (no handle / app id): skip, never crash
                counts["skipped_malformed"] += 1
                continue
            counts["scanned"] += 1
            for k in TEXT_FIELDS:             # live feeds often return null text fields
                if k in item and item[k] is None:
                    item[k] = ""
            why = exclusion_reason(brand, res.kind, item)
            if why:
                counts["excluded_official" if why == "official" else "excluded_allowlisted"] += 1
                continue
            ev = {"social": evaluate_social, "app": evaluate_app, "domain": evaluate_domain}[res.kind]
            det = ev(brand, item, b_hash, source=res.source)
            if det is None:
                counts["no_identity_signal"] += 1
            elif det.score < threshold:
                counts["below_threshold"] += 1
            else:
                counts["flagged"] += 1
                rep.detections.append(det)
                if store and store.upsert_detection(brand.name, det):
                    counts["new"] += 1
    rep.detections.sort(key=lambda d: -d.score)
    rep.summary = counts
    if store:
        store.log_run(brand.name, counts, rep.sources)
    return rep
