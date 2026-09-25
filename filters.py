"""Referans oran profilleri.

Türkiye-Fransa 25.09.2026 → deplasman kazanır
Norveç-Danimarka 24.09.2026 → KG Var (3-2 bitti)
"""
from __future__ import annotations

# İddaa kapanışına yakın bant. Dar tut: şablon sapmasın.
PROFILES = [
    {
        "id": "dep_tur_fra",
        "name": "Deplasman (TR-FRA şablonu)",
        "selection": "MS 2",
        "key": "a",
        "ref_match": "Türkiye - Fransa 25.09.2026 UNL",
        "ref_odds": {"h": 7.04, "d": 5.55, "a": 1.46, "o25": 1.46, "u25": 3.18},
        "need": [
            ("a", 1.38, 1.58),
            ("h", 5.80, 9.20),
            ("d", 4.70, 6.40),
        ],
        "sample": 13,
        "wins": 10,
        "hit_percent": 76.9,
        "why": "MS2 1.38-1.58, ev 5.80-9.20, X 4.70-6.40. TR-FRA fiyatı. Havuzda 13 maç / 10 deplasman.",
    },
    {
        "id": "kg_nor_den",
        "name": "KG Var (NOR-DEN şablonu)",
        "selection": "KG Var",
        "key": "btts",
        "ref_match": "Norveç - Danimarka 24.09.2026 UNL 3-2",
        "ref_odds": {"h": 1.47, "d": 3.86, "a": 4.24, "o25": 1.37, "u25": 2.25, "btts": 1.42},
        "need": [
            ("o25", 1.28, 1.50),
            ("u25", 2.00, 2.55),
        ],
        "optional": [
            ("btts", 1.32, 1.55),
        ],
        "sample": 119,
        "wins": 69,
        "hit_percent": 58.0,
        "why": "2,5Ü 1.28-1.50 ve 2,5A 2.00-2.55 (NOR-DEN: Üst 1.37 / KG 1.42). KG oranı varsa 1.32-1.55. Havuzda 2,5Ü bandında KG %58.",
    },
    {
        "id": "ev_bar_rac",
        "name": "Ev + üst + KG (BAR-RAC 7-2)",
        "selection": "MS 1",
        "key": "h",
        "keys": ["h", "o25", "btts"],
        "ref_match": "Barcelona - Racing Santander 16.09.2026 7-2",
        "ref_odds": {"h": 1.12, "d": 13.0, "a": 21.0, "o25": 1.11, "btts": 1.67},
        "need": [
            ("h", 1.05, 1.28),
            ("a", 12.0, 35.0),
            ("o25", 1.05, 1.22),
        ],
        "sample": 6,
        "wins": 5,
        "hit_percent": 83.3,
        "why": "Kısa ev + ölü 2,5Ü. BAR-RAC İddaa/piyasa ~1.12 / 13 / 21, Üst ~1.11, KG ~1.67. 7-2. Havuz 6/5 ev.",
    },
    {
        "id": "dep_lev_bar",
        "name": "Dep + üst + KG (LEV-BAR 2-4)",
        "selection": "MS 2",
        "key": "a",
        "keys": ["a", "o25", "btts"],
        "ref_match": "Levante - Barcelona 13.09.2026 2-4",
        "ref_odds": {"h": 14.0, "d": 8.5, "a": 1.20, "o25": 1.22, "btts": 1.55},
        "need": [
            ("a", 1.12, 1.28),
            ("h", 8.0, 18.0),
            ("o25", 1.15, 1.32),
        ],
        "sample": 5,
        "wins": 4,
        "hit_percent": 80.0,
        "why": "Kısa deplasman favori + gol. LEV-BAR ~14 / 8.5 / 1.20, Üst ~1.22. 2-4 KG. Havuz 5/4 MS2.",
    },
    {
        "id": "ev_fb_eyup",
        "name": "Ev + üst (FB-EYP 8-0)",
        "selection": "2,5 Üst",
        "key": "o25",
        "keys": ["h", "o25"],
        "ref_match": "Fenerbahçe - Eyüpspor 20.09.2026 8-0",
        "ref_odds": {"h": 1.19, "d": 7.32, "a": 15.25, "o25": 1.36, "u25": 2.54, "btts": 2.08, "nobtts": 1.44},
        "need": [
            ("h", 1.12, 1.28),
            ("a", 10.0, 18.0),
            ("o25", 1.28, 1.50),
        ],
        "sample": 15,
        "wins": 10,
        "hit_percent": 66.7,
        "why": "İddaa: MS1 kapanışta düşmüş, X 7.32 / MS2 15.25, 2,5Ü 1.36, KG Yok 1.44. 8-0. Havuzda üst %67, ev %73. KG bu şablonda yok.",
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
    hit, miss = [], []
    for rule in PROFILES:
        checks = []
        ok = True
        for key, lo, hi in rule["need"]:
            v = _odd(q.get(key))
            passed = v is not None and lo <= v <= hi
            if not passed:
                ok = False
            checks.append({"key": key, "odds": v, "range": [lo, hi], "passed": passed})
        opt_ok = True
        for key, lo, hi in rule.get("optional") or []:
            v = _odd(q.get(key))
            if v is None:
                checks.append({"key": key, "odds": None, "range": [lo, hi], "passed": None})
                continue
            passed = lo <= v <= hi
            if not passed:
                opt_ok = False
            checks.append({"key": key, "odds": v, "range": [lo, hi], "passed": passed})
        row = {
            **{k: rule[k] for k in ("id", "name", "selection", "key", "ref_match", "ref_odds",
                                     "sample", "wins", "hit_percent", "why")},
            "keys": rule.get("keys") or [rule.get("key")],
            "checks": checks,
            "match": bool(ok and opt_ok),
        }
        (hit if row["match"] else miss).append(row)
    return hit


def annotate(q: dict | None) -> dict:
    hits = match_profiles(q)
    return {
        "ok": True,
        "hits": hits,
        "labels": [x["id"] for x in hits],
        "text": "; ".join(x["name"] for x in hits) if hits else None,
    }
