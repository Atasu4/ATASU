"""pipeline v1.1 — standing λ + form proxy."""
from __future__ import annotations


def ingest_live_events(events, minute=None, score=None):
    alert = None
    try:
        m = int(minute) if minute is not None else None
    except Exception:
        m = None
    if m is not None and 60 <= m <= 75:
        alert = "60-75 pencere: 2. yari gol / late over kontrol"
    return {"ok": bool(events), "minute": minute, "score": score, "alert_60_75": alert, "note": "event"}


def empty_live():
    return {"ok": False, "note": "Canli feed yok"}


def build_pipeline(home, away, standing=None, extra=None, league="", live_events=None, minute=None, score=None, model_probs=None):
    standing = standing or {}
    extra = extra or standing.get("extra") or {}
    an = standing.get("analysis") or {}
    flags = []
    if not an.get("exp_total"):
        flags.append("lambda tablo yok")
    hop = an.get("home_opta") or {}
    aop = an.get("away_opta") or {}
    if not hop and not aop:
        flags.append("Opta yok")
    if extra.get("ok"):
        flags.append("fd.csv bagli")
    if an.get("npxg_total") is not None:
        flags.append(f"npxG {an.get('npxg_src') or 'proxy'}")
    live = ingest_live_events(live_events, minute, score) if live_events else empty_live()
    return {
        "ok": True,
        "version": "pipeline-1.1",
        "home": home,
        "away": away,
        "league": league,
        "metrics": {
            "home": {"npxG_pg": hop.get("npxg_pg") or hop.get("sot_pg"), "npxGA_pg": hop.get("npxga_pg"), "shots_pg": hop.get("shots_pg"), "src": hop.get("npxg_src")},
            "away": {"npxG_pg": aop.get("npxg_pg") or aop.get("sot_pg"), "npxGA_pg": aop.get("npxga_pg"), "shots_pg": aop.get("shots_pg"), "src": aop.get("npxg_src")},
            "match_npxG": an.get("npxg_total") or an.get("exp_total"),
            "npxg_home": an.get("npxg_home"),
            "npxg_away": an.get("npxg_away"),
            "combo_o25": an.get("combo_o25"),
            "combo_kg": an.get("combo_kg"),
        },
        "context": {"weather": {"ok": False}, "travel": None, "referee": {"ok": False}},
        "live": live,
        "flags": flags or ["ok"],
        "disclaimer": "npxG: Opta alan varsa resmi; yoksa SoT/şut proxy. Understat yok.",
    }


def lines_from_pipeline(p):
    if not p:
        return []
    m = p.get("metrics") or {}
    bits = [f"npxG maç {m.get('match_npxG')} (ev {m.get('npxg_home')} / dep {m.get('npxg_away')})"]
    if m.get("combo_o25") is not None:
        bits.append(f"taraf 2.5U %{m['combo_o25']}")
    if m.get("combo_kg") is not None:
        bits.append(f"taraf KG %{m['combo_kg']}")
    flags = p.get("flags") or []
    if flags:
        bits.append(" · ".join(flags))
    return bits
