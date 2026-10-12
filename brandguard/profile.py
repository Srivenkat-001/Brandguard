"""Brand profile: the single source of truth for what is *legitimate*.

Detection reads from it in two ways:
  1. to know what to look for (names, aliases, domains, logo, keywords)
  2. to know what to EXCLUDE (official accounts, official apps / developer ids,
     analyst-approved allowlist), so official assets are never flagged.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .textmatch import squash

PLATFORMS = ["x", "instagram", "facebook", "linkedin", "telegram", "youtube", "tiktok"]
STORES = ["google_play", "app_store"]
_PLATFORM_ALIASES = {"twitter": "x", "fb": "facebook", "ig": "instagram", "insta": "instagram",
                     "play": "google_play", "playstore": "google_play", "googleplay": "google_play",
                     "ios": "app_store", "appstore": "app_store", "apple": "app_store"}
_DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9-]{1,63}\.)+[a-z]{2,}$")


def norm_platform(p: str) -> str:
    p = (p or "").strip().lower().replace(" ", "_")
    return _PLATFORM_ALIASES.get(p, p)


def norm_handle(h: str) -> str:
    h = (h or "").strip().lower()
    h = re.sub(r"^https?://[^/]+/", "", h)       # accept a pasted URL
    h = h.strip("/@ ").split("/")[-1].split("?")[0]
    return h.lstrip("@")


def norm_domain(d: str) -> str:
    d = (d or "").strip().lower()
    d = re.sub(r"^https?://", "", d).split("/")[0]
    return d[4:] if d.startswith("www.") else d


@dataclass
class OfficialAccount:
    platform: str
    handle: str


@dataclass
class OfficialApp:
    store: str
    app_id: str          # Google Play package name or App Store bundle id / track id
    name: str = ""


@dataclass
class OfficialDeveloper:
    name: str
    developer_id: str = ""     # store-issued id; names alone are spoofable


@dataclass
class BrandProfile:
    name: str
    domains: list[str] = field(default_factory=list)
    description: str = ""
    logo_path: str = ""
    aliases: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    official_accounts: list[OfficialAccount] = field(default_factory=list)
    official_apps: list[OfficialApp] = field(default_factory=list)
    official_developers: list[OfficialDeveloper] = field(default_factory=list)
    allowlist: list[str] = field(default_factory=list)    # "kind:platform:ref" approved by an analyst
    base_dir: str = "."                                    # resolves relative logo paths

    # ------------------------------------------------------------ derived
    def match_names(self) -> list[str]:
        names = [self.name, *self.aliases]
        for d in self.domains:
            label = norm_domain(d).split(".")[0]
            if label:
                names.append(label)
        seen, out = set(), []
        for n in names:
            k = squash(n)
            if k and k not in seen:
                seen.add(k)
                out.append(n)
        return out

    def logo_file(self) -> Path | None:
        if not self.logo_path:
            return None
        p = Path(self.logo_path)
        if not p.is_absolute():
            p = Path(self.base_dir) / p
        return p if p.exists() else None

    # --------------------------------------------------------- exclusions
    def is_official_account(self, platform: str, handle: str) -> bool:
        p, h = norm_platform(platform), norm_handle(handle)
        return any(norm_platform(a.platform) == p and norm_handle(a.handle) == h
                   for a in self.official_accounts)

    def is_official_app(self, app_id: str, developer_id: str = "") -> bool:
        if any(a.app_id.strip().lower() == (app_id or "").strip().lower() for a in self.official_apps):
            return True
        return bool(developer_id) and any(d.developer_id and d.developer_id == str(developer_id)
                                          for d in self.official_developers)

    def developer_name_is_official(self, name: str) -> bool:
        return any(squash(d.name) == squash(name) for d in self.official_developers if d.name)

    def is_allowlisted(self, kind: str, platform: str, ref: str) -> bool:
        key = f"{kind}:{norm_platform(platform)}:{(ref or '').strip().lower()}"
        return key in {a.lower() for a in self.allowlist}

    # ------------------------------------------------------- validation
    def validate(self) -> list[tuple[str, str]]:
        """Return [(severity, message)]; severity is 'error' or 'warning'."""
        issues: list[tuple[str, str]] = []
        add = lambda s, m: issues.append((s, m))
        if not self.name.strip():
            add("error", "Brand name is required.")
        if not self.domains:
            add("warning", "No official domain: link/domain look-alike checks are disabled.")
        for d in self.domains:
            if not _DOMAIN_RE.match(norm_domain(d)):
                add("error", f"'{d}' is not a valid domain (example: example.com).")
        if not self.logo_path:
            add("warning", "No logo: logo-impersonation checks are disabled.")
        elif not self.logo_file():
            add("error", f"Logo file not found: {self.logo_path}")
        if not self.official_accounts and not self.official_apps:
            add("warning", "No official accounts or apps listed: nothing can be excluded, "
                           "so your own assets may be flagged.")
        for a in self.official_accounts:
            if norm_platform(a.platform) not in PLATFORMS:
                add("error", f"Unsupported platform '{a.platform}'. Use one of: {', '.join(PLATFORMS)}.")
            if not norm_handle(a.handle):
                add("error", f"Empty handle for platform '{a.platform}'.")
        for a in self.official_apps:
            if norm_platform(a.store) not in STORES:
                add("error", f"Unsupported store '{a.store}'. Use one of: {', '.join(STORES)}.")
            if not a.app_id.strip():
                add("error", "An official app is missing its app id / bundle id.")
        if self.official_apps and not any(d.developer_id for d in self.official_developers):
            add("warning", "No official developer id: apps are excluded only by exact app id. "
                           "Publisher names alone are never trusted (they can be spoofed).")
        keys = [(norm_platform(a.platform), norm_handle(a.handle)) for a in self.official_accounts]
        if len(keys) != len(set(keys)):
            add("warning", "Duplicate official accounts listed.")
        return issues

    def has_errors(self) -> bool:
        return any(s == "error" for s, _ in self.validate())

    # ------------------------------------------------------ persistence
    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("base_dir", None)
        return d

    @classmethod
    def from_dict(cls, d: dict, base_dir: str = ".") -> "BrandProfile":
        return cls(
            name=d.get("name", ""),
            domains=[norm_domain(x) for x in d.get("domains", []) if x.strip()],
            description=d.get("description", ""),
            logo_path=d.get("logo_path", ""),
            aliases=[x for x in d.get("aliases", []) if x.strip()],
            keywords=[x for x in d.get("keywords", []) if x.strip()],
            official_accounts=[OfficialAccount(norm_platform(a["platform"]), norm_handle(a["handle"]))
                               for a in d.get("official_accounts", []) if a.get("handle")],
            official_apps=[OfficialApp(norm_platform(a["store"]), a["app_id"].strip(), a.get("name", ""))
                           for a in d.get("official_apps", []) if a.get("app_id")],
            official_developers=[OfficialDeveloper(a.get("name", ""), str(a.get("developer_id", "")))
                                 for a in d.get("official_developers", []) if a.get("name") or a.get("developer_id")],
            allowlist=list(d.get("allowlist", [])),
            base_dir=base_dir,
        )

    @classmethod
    def load(cls, path: str | Path) -> "BrandProfile":
        path = Path(path)
        return cls.from_dict(json.loads(path.read_text()), base_dir=str(path.parent))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))
