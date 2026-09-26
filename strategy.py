"""İddaa masa stratejisi. Şablonlar boş; yeni referanslar filters.PROFILES'tan gelir."""
from __future__ import annotations

NAMES = {"h": "MS 1", "d": "MS X", "a": "MS 2", "o25": "2,5 Üst", "u25": "2,5 Alt",
         "btts": "KG Var", "nobtts": "KG Yok", "o35": "3,5 Üst", "u35": "3,5 Alt"}

SIEVES = []


def _f(v):
    try:
        x = float(v)
        return x if 1.01 <= x <= 80 else None
    except Exception:
        return None


def _dead_ms(odd):
    x = _f(odd)
    return x is not None and x < 1.22


def _dead_ou(odd):
    x = _f(odd)
    return x is not None and x < 1.22


def pick(q: dict | None, title: str = "") -> dict:
    import filters
    q = q or {}
    hits = filters.match_profiles(q)
    if not hits:
        return {
            "karar": "GEC",
            "key": None,
            "name": None,
            "odds": None,
            "strategy": None,
            "label": None,
            "why": "Referans şablon yok veya fiyat oturmadı.",
            "profiles": [],
        }
    h = hits[0]
    key = h.get("key") or "h"
    if not _f(q.get(key)):
        for cand in hits:
            for k in (cand.get("keys") or []) + [cand.get("key"), "o25", "a", "h"]:
                if k and _f(q.get(k)):
                    h, key = cand, k
                    break
            else:
                continue
            break
    odd = _f(q.get(key))
    dead = (_dead_ms(odd) if key in ("h", "a") else _dead_ou(odd)) if odd else False
    if dead or odd is None:
        return {
            "karar": "GEC",
            "key": key,
            "name": NAMES.get(key) or h.get("selection"),
            "odds": odd,
            "strategy": h.get("id"),
            "label": h.get("name"),
            "why": "Şablon oturdu ama fiyat yok/ölü.",
            "profiles": [x.get("id") for x in hits],
        }
    return {
        "karar": "OYNA",
        "key": key,
        "name": NAMES.get(key) or h.get("selection"),
        "odds": odd,
        "strategy": h.get("id"),
        "label": h.get("name"),
        "why": h.get("why") or "",
        "profiles": [x.get("id") for x in hits],
    }
