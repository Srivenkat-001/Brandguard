"""Look-alike name detection.

Explainable, rule-based matching (no black box) so every flag can show *why*:
  identical name, spacing change, homoglyph substitution, character swap /
  typo, added words (support / official / rewards ...), word-order change.

Over-flagging is controlled by: minimum-length guards, a weighted edit
distance with a tight budget, token-boundary checks, and a down-weighted
"commentary" class (e.g. "<Brand> Fans", "<Brand> News").
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# True homoglyphs (Cyrillic / Greek / misc) folded to Latin at zero cost.
UNICODE_FOLD = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "һ": "h", "ɡ": "g", "ɑ": "a",
    "ο": "o", "α": "a", "ρ": "p", "ν": "v", "ι": "i", "κ": "k", "τ": "t",
    "ϲ": "c", "ı": "i", "ℓ": "l",
}

# Visually confusable ASCII pairs: substitution costs 0.3 instead of 1.
_CONF_PAIRS = [("0", "o"), ("1", "l"), ("1", "i"), ("l", "i"), ("5", "s"),
               ("3", "e"), ("4", "a"), ("7", "t"), ("8", "b"), ("9", "g"),
               ("q", "g"), ("u", "v")]
CONFUSABLE = {frozenset(p) for p in _CONF_PAIRS}

SUSPICIOUS_TOKENS = {
    "support", "official", "officials", "verify", "verified", "login", "signin",
    "secure", "security", "reward", "rewards", "claim", "giveaway", "helpdesk",
    "helpline", "help", "care", "customercare", "kyc", "refund", "wallet",
    "offer", "offers", "bonus", "prize", "loan", "loans", "cashback", "service",
    "services", "update", "online", "team", "hq", "app", "mobile", "pay",
    "payments", "cash", "free", "lucky", "winner", "airdrop", "crypto",
}
SUSPICIOUS_SUBSTR = ("support", "official", "verify", "reward", "giveaway",
                     "helpdesk", "helpline", "customercare", "cashback", "secure")
NEUTRAL_TOKENS = {
    "news", "blog", "review", "reviews", "fan", "fans", "fanclub", "community",
    "forum", "jobs", "careers", "alumni", "memes", "discussion", "customers",
    "users", "watch", "stories", "podcast",
}


# --------------------------------------------------------------------- utils
def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def fold(s: str) -> str:
    s = _strip_accents(s).lower()
    s = "".join(UNICODE_FOLD.get(c, c) for c in s)
    # mid-word symbol substitutions: b@nk, $ecure
    s = re.sub(r"(?<=[a-z0-9])[@$](?=[a-z0-9])",
               lambda m: {"@": "a", "$": "s"}[m.group()], s)
    return s


def tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(s))


def squash(s: str) -> str:
    return "".join(tokens(s))


def squash_plain(s: str) -> str:
    """Lowercase + alnum only, *without* homoglyph folding (detects substitutions)."""
    return re.sub(r"[^a-z0-9]", "", _strip_accents(s).lower())


def _visual(s: str) -> str:
    return s.replace("rn", "m").replace("vv", "w")


def _sub_cost(a: str, b: str) -> float:
    if a == b:
        return 0.0
    return 0.3 if frozenset((a, b)) in CONFUSABLE else 1.0


def weighted_distance(a: str, b: str) -> float:
    """Damerau-Levenshtein (adjacent transposition = 1) with confusable-aware substitution."""
    la, lb = len(a), len(b)
    d = [[0.0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = float(i)
    for j in range(lb + 1):
        d[0][j] = float(j)
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1,
                          d[i - 1][j - 1] + _sub_cost(a[i - 1], b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]


def _contig_index(sub: list[str], seq: list[str]) -> int:
    for i in range(len(seq) - len(sub) + 1):
        if seq[i:i + len(sub)] == sub:
            return i
    return -1


# -------------------------------------------------------------------- result
@dataclass
class Lookalike:
    score: float = 0.0                       # 0..1 confidence that this imitates the brand
    kinds: list[str] = field(default_factory=list)
    matched_name: str = ""

    @property
    def hit(self) -> bool:
        return self.score >= 0.5

    def describe(self) -> str:
        return f"{', '.join(self.kinds)} of '{self.matched_name}'" if self.kinds else ""


def _is_suspicious(tok: str) -> bool:
    return tok in SUSPICIOUS_TOKENS or any(s in tok for s in SUSPICIOUS_SUBSTR)


def _concat_run(c_tok: list[str], b_sq: str):
    """Find a run of candidate tokens whose concatenation equals the brand string (e.g. 'veridianbank')."""
    for i in range(len(c_tok)):
        acc = ""
        for j in range(i, len(c_tok)):
            acc += c_tok[j]
            if acc == b_sq:
                return i, j + 1
            if len(acc) >= len(b_sq):
                break
    return None


def _added_words(c_tok, c_sq, b_tok, b_sq) -> Lookalike | None:
    i = _contig_index(b_tok, c_tok)
    if i >= 0:
        extras = c_tok[:i] + c_tok[i + len(b_tok):]
    elif (run := _concat_run(c_tok, b_sq)) is not None:
        extras = c_tok[:run[0]] + c_tok[run[1]:]
    elif len(b_sq) >= 6 and b_sq in c_sq:
        extras = [c_sq.replace(b_sq, "", 1)]
    else:
        return None
    extras = [e for e in extras if e]
    if not extras:
        return None
    sus = [e for e in extras if _is_suspicious(e)]
    if sus:
        return Lookalike(0.85, [f"added words ({', '.join(sus)})"])
    if all(e.isdigit() for e in extras):
        return Lookalike(0.70, ["added numbers"])
    if all(e in NEUTRAL_TOKENS for e in extras):
        return Lookalike(0.30, ["commentary-style name (low confidence)"])
    # Generic extra words ("Veridian Bakery", "Veridian Credit Union") only count against a
    # *distinctive* name: a multi-word brand name or a long single-word name. A short
    # single-word alias would otherwise flag every unrelated business sharing that word.
    if len(b_tok) < 2 and len(b_sq) < 10:
        return None
    return Lookalike(0.60, [f"added words ({' '.join(extras)})"])


def _compare(cand: str, brand: str) -> Lookalike:
    c_tok, b_tok = tokens(cand), tokens(brand)
    c_sq, b_sq = "".join(c_tok), "".join(b_tok)
    if not c_sq or not b_sq:
        return Lookalike()
    options: list[Lookalike] = []

    if c_sq == b_sq:
        if squash_plain(cand) != squash_plain(brand):
            options.append(Lookalike(0.93, ["character substitution (homoglyph)"]))
        elif cand.strip().lower() == brand.strip().lower():
            options.append(Lookalike(0.90, ["identical name"]))
        elif c_tok == b_tok:
            options.append(Lookalike(0.85, ["punctuation/case variant"]))
        else:
            options.append(Lookalike(0.90, ["spacing change"]))
    else:
        if len(b_tok) > 1 and sorted(c_tok) == sorted(b_tok):
            options.append(Lookalike(0.80, ["word order change"]))
        if _visual(c_sq) == _visual(b_sq):
            options.append(Lookalike(0.90, ["visual substitution (rn/m, vv/w)"]))
        added = _added_words(c_tok, c_sq, b_tok, b_sq)
        if added:
            options.append(added)
        if len(b_sq) >= 5:
            d = weighted_distance(c_sq, b_sq)
            limit = 1.0 if len(b_sq) <= 8 else 2.0
            if d <= limit:
                if d < 1:
                    kind = "character substitution (look-alike glyph)"
                elif len(c_sq) == len(b_sq):
                    kind = ("character swap" if sorted(c_sq) == sorted(b_sq)
                            else "character substitution")
                elif len(c_sq) > len(b_sq):
                    kind = "extra character(s)"
                else:
                    kind = "missing character(s)"
                options.append(Lookalike(0.90 if d < 1 else (0.88 if d <= 1 else 0.72), [kind]))

    if not options:
        return Lookalike()
    best = max(options, key=lambda o: o.score)
    best.matched_name = brand
    return best


def lookalike(candidate: str, brand_names: list[str]) -> Lookalike:
    """Best look-alike verdict of `candidate` against any of the brand's names."""
    best = Lookalike()
    for bn in brand_names:
        r = _compare(candidate or "", bn)
        if r.score > best.score:
            best = r
    return best


def mentions_brand(text: str, brand_names: list[str]) -> bool:
    t = tokens(text or "")
    for bn in brand_names:
        b = tokens(bn)
        if b and _contig_index(b, t) >= 0:
            return True
        if len("".join(b)) >= 6 and "".join(b) in "".join(t):
            return True
    return False


# ------------------------------------------------------------------ variants
_SUFFIXES = ["support", "official", "app", "rewards", "login", "care", "help"]
_GLYPH = {"o": "0", "l": "1", "i": "1", "e": "3", "a": "4", "s": "5"}


def generate_variants(name: str, limit: int = 40) -> list[str]:
    """dnstwist-style permutations, used to seed live store / social searches."""
    base = " ".join(tokens(name))
    flat = base.replace(" ", "")
    out: list[str] = []

    def add(v: str):
        if v and v != base and v not in out:
            out.append(v)

    add(flat)                                   # spacing
    add(base.replace(" ", "-"))
    add(base.replace(" ", "_"))
    for sfx in _SUFFIXES:                       # added words
        add(f"{base} {sfx}")
    for i in range(len(flat) - 1):              # adjacent swaps
        if flat[i] != flat[i + 1]:
            add(flat[:i] + flat[i + 1] + flat[i] + flat[i + 2:])
    for i, ch in enumerate(flat):               # glyph swaps
        if ch in _GLYPH:
            add(flat[:i] + _GLYPH[ch] + flat[i + 1:])
    for i in range(1, len(flat) - 1):           # dropped char
        add(flat[:i] + flat[i + 1:])
    return out[:limit]
