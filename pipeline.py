"""pipeline v1.2 — tablo λ + xG + bağlam + canlı masa."""
from __future__ import annotations

import context_layer
import live_desk


def ingest_live_events(events, minute=None, score=None, pick_key=None, pre_karar=""):
    pack = live_desk.read(minute, score, pick_key=pick_key, pre_karar=pre_karar)
    if events and not pack.get("ok"):
        pack["ok"] = True
        pack["note"] = pack.get("note") or "event"
    return pack


def empty_live():
    return {"ok": False, "note": "Canlı dakika yok"}


def build_pipeline(home, away, standing=None, extra=None, league="", live_events=None,
                   minute=None, score=None, model_probs=None, news=None):
    standing = standing or {}
    extra = extra or standing.get("extra") or {}
    an = standing.get("analysis") or {}
    flags = []
    if not an.get("exp_total"):
        flags.append("lambda tablo yok")
    hop = an.get("home_opta") or {}
    aop = an.get("away_opta") or {}
    if not hop and not aop and an.get("npxg_src") != "understat":
        flags.append("Opta yok")
    if extra.get("ok"):
        flags.append("fd.csv bagli")
    if an.get("npxg_total") is not None:
        flags.append(f"npxG {an.get('npxg_src') or 'proxy'}")
    try:
        ctx = context_layer.build(home or "", away or "", standing=standing, news=news)
    except Exception as e:
        ctx = {"ok": False, "note": str(e)[:80], "flags": []}
    flags.extend(ctx.get("flags") or [])
    live = ingest_live_events(live_events, minute, score) if (live_events or minute is not None) else empty_live()
    if live.get("window_60_75"):
        flags.append("60-75 pencere")
    return {
        "ok": True,
        "version": "pipeline-1.2",
        "home": home,
        "away": away,
        "league": league,
        "metrics": {
            "home": {"npxG_pg": hop.get("npxg_pg") or hop.get("sot_pg"), "npxGA_pg": hop.get("npxga_pg"), "shots_pg": hop.get("shots_pg"), "src": hop.get("npxg_src") or an.get("npxg_src")},
            "away": {"npxG_pg": aop.get("npxg_pg") or aop.get("sot_pg"), "npxGA_pg": aop.get("npxga_pg"), "shots_pg": aop.get("shots_pg"), "src": aop.get("npxg_src") or an.get("npxg_src")},
            "match_npxG": an.get("npxg_total") or an.get("exp_total"),
            "npxg_home": an.get("npxg_home"),
            "npxg_away": an.get("npxg_away"),
            "combo_o25": an.get("combo_o25"),
            "combo_kg": an.get("combo_kg"),
        },
        "context": {
            "weather": ctx.get("weather") or {"ok": False},
            "travel": ctx.get("travel"),
            "referee": ctx.get("referee") or {"ok": False},
            "derby": ctx.get("derby"),
            "news": ctx.get("news") or {"ok": False},
            "flags": ctx.get("flags") or [],
        },
        "live": live,
        "flags": flags or ["ok"],
        "disclaimer": "npxG: Opta resmi > Understat > SoT proxy. Hava yalnız anahtar varsa.",
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
    ctx = p.get("context") or {}
    if ctx.get("derby"):
        bits.append("derbi")
    tr = ctx.get("travel") or {}
    if tr.get("label"):
        bits.append(tr["label"])
    flags = p.get("flags") or []
    if flags:
        bits.append(" · ".join(flags))
    live = p.get("live") or {}
    if live.get("idea"):
        bits.append(live["idea"])
    return bits
