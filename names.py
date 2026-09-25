"""Takım adı katmanı — Mackolik / football-data / Understat eşlemesi."""
from __future__ import annotations

import re

ALIASES = {
    "besiktas": "besiktas",
    "bjk": "besiktas",
    "fenerbahce": "fenerbahce",
    "fb": "fenerbahce",
    "galatasaray": "galatasaray",
    "gs": "galatasaray",
    "trabzonspor": "trabzonspor",
    "ts": "trabzonspor",
    "basaksehir": "basaksehir",
    "istanbul basaksehir": "basaksehir",
    "ibfk": "basaksehir",
    "konyaspor": "konyaspor",
    "sivasspor": "sivasspor",
    "alanyaspor": "alanyaspor",
    "antalyaspor": "antalyaspor",
    "kasimpasa": "kasimpasa",
    "kayserispor": "kayserispor",
    "rizespor": "rizespor",
    "caykur rizespor": "rizespor",
    "goztepe": "goztepe",
    "samsunspor": "samsunspor",
    "eyupspor": "eyupspor",
    "gaziantep": "gaziantep",
    "gaziantep fk": "gaziantep",
    "hatayspor": "hatayspor",
    "man utd": "manchester united",
    "man united": "manchester united",
    "manchester utd": "manchester united",
    "man city": "manchester city",
    "spurs": "tottenham",
    "wolves": "wolverhampton",
    "newcastle utd": "newcastle",
    "west ham": "west ham",
    "nottm forest": "nottingham forest",
    "nottingham": "nottingham forest",
    "brighton": "brighton",
    "leicester": "leicester",
    "inter": "inter",
    "internazionale": "inter",
    "ac milan": "milan",
    "atletico": "atletico madrid",
    "ath madrid": "atletico madrid",
    "atletico madrid": "atletico madrid",
    "real madrid": "real madrid",
    "barcelona": "barcelona",
    "barca": "barcelona",
    "bayern": "bayern munich",
    "bayern munich": "bayern munich",
    "dortmund": "borussia dortmund",
    "psg": "paris saint germain",
    "paris sg": "paris saint germain",
    "sporting": "sporting lisbon",
    "benfica": "benfica",
    "porto": "porto",
    "ajax": "ajax",
    "psv": "psv",
}


def fold(s: str) -> str:
    s = (s or "").casefold()
    table = str.maketrans("ıİiIâäöüûçşğ", "iiiiiaouucsg")
    s = s.translate(str.maketrans({
        "ı": "i", "i": "i", "İ": "i", "I": "i",
        "ö": "o", "ü": "u", "ş": "s", "ç": "c", "ğ": "g",
        "â": "a", "û": "u", "ä": "a",
    }))
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def canon(s: str) -> str:
    n = fold(s)
    if n in ALIASES:
        return ALIASES[n]
    for k, v in ALIASES.items():
        if k in n or n in k:
            return v
    drop = {"fc", "cf", "sk", "fk", "afc", "sc", "the", "de", "club", "spor", "sporlari"}
    parts = [p for p in n.split() if p and p not in drop]
    return " ".join(parts)


def score(a: str, b: str) -> float:
    ca, cb = canon(a), canon(b)
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 1.0
    if ca in cb or cb in ca:
        return 0.88
    ta, tb = set(ca.split()), set(cb.split())
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    if ta <= tb or tb <= ta:
        return 0.84
    if inter:
        return len(inter) / len(ta | tb)
    for x in ta:
        for y in tb:
            if len(x) >= 5 and len(y) >= 5 and (x.startswith(y[:5]) or y.startswith(x[:5])):
                return 0.72
    return 0.0


def same(a: str, b: str, thresh: float = 0.72) -> bool:
    return score(a, b) >= thresh
