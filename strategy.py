"""İddaa masa stratejisi: bugünün programı, tek iş, dört süzgeç."""
from __future__ import annotations

NAMES = {"h": "MS 1", "d": "MS X", "a": "MS 2", "o25": "2,5 Üst", "u25": "2,5 Alt",
         "btts": "KG Var", "nobtts": "KG Yok", "o35": "3,5 Üst", "u35": "3,5 Alt"}


def _f(v):
    try:
        x = float(v)
        return x if 1.01 <= x <= 80 else None
    except Exception:
        return None


def _in(v, lo, hi):
    x = _f(v)
    return x is not None and lo <= x <= hi


def _dead_ms(odd):
    x = _f(odd)
    return x is not None and x < 1.22


def _dead_ou(odd):
    x = _f(odd)
    return x is not None and x < 1.22


# Öncelik: dar şablon > genel süzgeç. Bir maçta tek satır.
SIEVES = [
    {
        "id": "iki_taraf_2",
        "name": "İki taraf 2+",
        "key": "o25",
        "need": lambda q: (
            _in(q.get("o25"), 1.35, 1.55)
            and _in(q.get("d"), 3.20, 4.20)
            and (
                (_in(q.get("h"), 1.35, 1.90) and (not _f(q.get("a")) or q.get("h") <= q.get("a")))
                or (_in(q.get("a"), 1.35, 1.90) and (not _f(q.get("h")) or q.get("a") <= q.get("h")))
            )
        ),
        "kill": lambda q: _dead_ou(q.get("o25")),
        "why": "Favori 1.35-1.90 + X 3.20-4.20 + 2,5Ü 1.35-1.55. Son hafta iki taraf 2+ gol seti.",
    },
    {
        "id": "dep_kisa",
        "name": "Deplasman favori",
        "key": "a",
        "need": lambda q: _in(q.get("a"), 1.30, 1.80) and _in(q.get("h"), 4.80, 10.0),
        "kill": lambda q: _dead_ms(q.get("a")),
        "why": "MS2 1.30-1.80, ev 4.80-10. TR-FRA tipi.",
    },
    {
        "id": "ev_kisa",
        "name": "Ev favori",
        "key": "h",
        "need": lambda q: _in(q.get("h"), 1.30, 1.80) and _in(q.get("a"), 4.80, 12.0),
        "kill": lambda q: _dead_ms(q.get("h")),
        "why": "MS1 1.30-1.80. Ölü 1.15 değil.",
    },
    {
        "id": "tempo_ust",
        "name": "Tempo üst",
        "key": "o25",
        "need": lambda q: _in(q.get("o25"), 1.35, 1.70),
        "kill": lambda q: _dead_ou(q.get("o25")),
        "why": "2,5 Üst 1.35-1.70. 1.11 ölü fiyat.",
    },
    {
        "id": "kg_acik",
        "name": "KG açık",
        "key": "btts",
        "need": lambda q: (
            _in(q.get("btts"), 1.40, 1.75)
            or (_in(q.get("o25"), 1.28, 1.55) and _in(q.get("u25"), 1.95, 2.60)
                and not _in(q.get("h"), 1.05, 1.28) and not _in(q.get("a"), 1.05, 1.28))
        ),
        "kill": lambda q: False,
        "why": "KG 1.40-1.75 veya NOR-DEN tipi 2,5 bandı (ezme favori değil).",
    },
    {
        "id": "kilit_alt",
        "name": "Kilit alt",
        "key": "u25",
        "need": lambda q: _in(q.get("u25"), 1.20, 1.45) and (_f(q.get("o25")) or 9) >= 1.70,
        "kill": lambda q: False,
        "why": "2,5 Alt kısa, üst şişmiş. Tempo kilit.",
    },
]


def pick(q: dict | None, title: str = "") -> dict:
    """Tek satır. Şablon varsa o; yoksa süzgeç; yoksa GEÇ."""
    import filters
    q = q or {}
    hits = filters.match_profiles(q)
    if hits:
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
        if dead:
            return {
                "karar": "GEC",
                "key": key,
                "name": h.get("selection"),
                "odds": odd,
                "strategy": h.get("id"),
                "label": h.get("name"),
                "why": "Şablon oturdu ama fiyat ölü (" + str(odd) + ").",
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
    for s in SIEVES:
        if not s["need"](q):
            continue
        key = s["key"]
        if key == "btts" and not _f(q.get("btts")):
            key = "o25" if _f(q.get("o25")) else "btts"
        odd = _f(q.get(key))
        if s["kill"](q) or odd is None:
            continue
        return {
            "karar": "OYNA",
            "key": key,
            "name": NAMES.get(key, key),
            "odds": odd,
            "strategy": s["id"],
            "label": s["name"],
            "why": s["why"],
            "profiles": [],
        }
    return {
        "karar": "GEC",
        "key": None,
        "name": None,
        "odds": None,
        "strategy": None,
        "label": None,
        "why": "Bugünün fiyatı hiçbir süzgece oturmadı.",
        "profiles": [],
    }
