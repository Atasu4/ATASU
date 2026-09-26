"""Referans oran profilleri — 25-26.09.2026 kupon seti (Mackolik İddaa)."""
from __future__ import annotations

PROFILES = [
    {
        "id": "ms1_nijer",
        "name": "MS 1 (Nijer-Lesotho)",
        "selection": "MS 1",
        "key": "h",
        "keys": ["h"],
        "ref_match": "Nijer - Lesotho 25.09.2026 AFCON 2-1",
        "ref_odds": {"h": 1.55, "d": 3.03, "a": 4.03, "u25": 1.43, "o25": 1.92},
        "need": [("h", 1.45, 1.70), ("d", 2.80, 3.30), ("a", 3.60, 4.50), ("o25", 1.70, 2.15)],
        "why": "Mackolik 1.55 / 3.03 / 4.03. MS1. 2-1 bitti.",
    },
    {
        "id": "gol_ruanda",
        "name": "Üst + KG (Ruanda-Liberya)",
        "selection": "2,5 Üst",
        "key": "o25",
        "keys": ["o25", "o35", "btts"],
        "ref_match": "Ruanda - Liberya 25.09.2026 AFCON 3-1",
        "ref_odds": {"h": 1.56, "d": 2.91, "a": 4.19, "u25": 1.30, "o25": 2.23},
        "need": [("h", 1.45, 1.70), ("u25", 1.22, 1.42), ("o25", 1.95, 2.55)],
        "why": "Mackolik MS 1.56/2.91/4.19, 2,5A 1.30 / Ü 2.23. Kupon 2,5Ü+3,5Ü+KG. 3-1.",
    },
    {
        "id": "o05_hellerup",
        "name": "0,5 Üst (Hellerup-Roskilde)",
        "selection": "2,5 Üst",
        "key": "o25",
        "keys": ["o25"],
        "ref_match": "Hellerup - Roskilde 25.09.2026 DAN2 1-1",
        "ref_odds": {"h": 5.01, "d": 3.99, "a": 1.30, "u25": 2.07, "o25": 1.36},
        "need": [("h", 4.50, 5.70), ("a", 1.22, 1.40), ("o25", 1.28, 1.48)],
        "why": "Mackolik MS2 1.30, 2,5Ü 1.36. Kupon 0,5Ü (bültende 0,5 yok, 2,5Ü yakın). 1-1.",
    },
    {
        "id": "u35_tur_fra",
        "name": "3,5 Alt (TR-FRA)",
        "selection": "3,5 Alt",
        "key": "u35",
        "keys": ["u35", "a"],
        "ref_match": "Türkiye - Fransa 25.09.2026 UNL 0-1",
        "ref_odds": {"h": 7.04, "d": 5.38, "a": 1.25, "u25": 2.91, "o25": 1.28},
        "need": [("a", 1.18, 1.35), ("o25", 1.22, 1.38), ("h", 5.80, 8.50)],
        "why": "Mackolik MS2 1.25, 2,5Ü 1.28. Kupon 3,5 Alt. 0-1.",
    },
    {
        "id": "u35_hun_ukr",
        "name": "3,5 Alt (MAC-UKR)",
        "selection": "3,5 Alt",
        "key": "u35",
        "keys": ["u35", "u25"],
        "ref_match": "Macaristan - Ukrayna 25.09.2026 UNL 0-1",
        "ref_odds": {"h": 2.31, "d": 2.84, "a": 2.55, "u25": 1.53, "o25": 1.91},
        "need": [("h", 2.10, 2.55), ("d", 2.60, 3.10), ("a", 2.30, 2.80), ("o25", 1.70, 2.15)],
        "why": "Mackolik 2.31/2.84/2.55, 2,5Ü 1.91. Kupon 3,5 Alt. 0-1.",
    },
    {
        "id": "msx_pol_bos",
        "name": "MS X (POL-BOS)",
        "selection": "MS X",
        "key": "d",
        "keys": ["d"],
        "ref_match": "Polonya - Bosna Hersek 25.09.2026 UNL 0-0",
        "ref_odds": {"h": 1.37, "d": 3.89, "a": 5.17, "u25": 1.93, "o25": 1.51},
        "need": [("h", 1.28, 1.50), ("d", 3.50, 4.40), ("a", 4.50, 6.20)],
        "why": "Mackolik 1.37/3.89/5.17, 2,5Ü 1.51. Kupon MS X + 0-0. 0-0.",
    },
    {
        "id": "ust_ita_bel",
        "name": "1,5/2,5 Üst (İTA-BEL)",
        "selection": "2,5 Üst",
        "key": "o25",
        "keys": ["o25"],
        "ref_match": "İtalya - Belçika 25.09.2026 UNL 0-2",
        "ref_odds": {"h": 1.95, "d": 3.19, "a": 2.85, "u25": 1.96, "o25": 1.50},
        "need": [("d", 2.95, 3.45), ("o25", 1.40, 1.62), ("h", 1.75, 2.20)],
        "why": "Mackolik 1.95/3.19/2.85, 2,5Ü 1.50. Kupon 1,5Ü+2,5Ü. 0-2.",
    },
    {
        "id": "u25_estrella",
        "name": "2,5 Alt (Estrella-LP C)",
        "selection": "2,5 Alt",
        "key": "u25",
        "keys": ["u25"],
        "ref_match": "Estrella - Las Palmas C 26.09.2026 Tercera 1-1",
        "ref_odds": {"h": 3.12, "d": 3.03, "a": 1.74, "u25": 1.70, "o25": 1.58},
        "need": [("a", 1.55, 1.95), ("u25", 1.55, 1.90), ("o25", 1.45, 1.75)],
        "why": "Mackolik 3.12/3.03/1.74, 2,5A 1.70. Kupon 2,5 Alt. 1-1.",
    },
    {
        "id": "u25_grenada",
        "name": "2,5 Alt (Grenada-Küba)",
        "selection": "2,5 Alt",
        "key": "u25",
        "keys": ["u25"],
        "ref_match": "Grenada - Küba 26.09.2026 CNL 0-3",
        "ref_odds": {"h": 2.68, "d": 2.77, "a": 2.05, "u25": 1.44, "o25": 1.91},
        "need": [("h", 2.40, 3.00), ("d", 2.50, 3.10), ("a", 1.85, 2.30), ("u25", 1.32, 1.58)],
        "why": "Mackolik 2.68/2.77/2.05, 2,5A 1.44. Kupon 2,5 Alt. Bu maç 0-3 kaçtı.",
    },
]


def _odd(v):
    try:
        f = float(v)
        return f if f > 1 else None
    except Exception:
        return None


def match_profiles(q: dict | None) -> list[dict]:
    q = q or {}
    hit = []
    for rule in PROFILES:
        checks = []
        ok = True
        for key, lo, hi in rule.get("need") or []:
            v = _odd(q.get(key))
            passed = v is not None and lo <= v <= hi
            if not passed:
                ok = False
            checks.append({"key": key, "odds": v, "range": [lo, hi], "passed": passed})
        for key, lo, hi in rule.get("optional") or []:
            v = _odd(q.get(key))
            if v is None:
                checks.append({"key": key, "odds": None, "range": [lo, hi], "passed": None})
                continue
            passed = lo <= v <= hi
            if not passed:
                ok = False
            checks.append({"key": key, "odds": v, "range": [lo, hi], "passed": passed})
        row = {
            **{k: rule[k] for k in ("id", "name", "selection", "key", "ref_match", "ref_odds", "why") if k in rule},
            "keys": rule.get("keys") or [rule.get("key")],
            "checks": checks,
            "match": bool(ok),
        }
        if row["match"]:
            hit.append(row)
    return hit


def annotate(q: dict | None) -> dict:
    hits = match_profiles(q)
    return {
        "ok": True,
        "hits": hits,
        "labels": [x.get("id") for x in hits],
        "text": "; ".join(x.get("name") or "" for x in hits) if hits else None,
    }
