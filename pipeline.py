"""pipeline v1 stubs used by app."""
def ingest_live_events(events, minute=None, score=None):
    return {"ok": bool(events), "minute": minute, "score": score, "alert_60_75": None, "note": "event"}
def empty_live():
    return {"ok": False, "note": "Canlı feed yok"}
def build_pipeline(home, away, standing=None, extra=None, league="", live_events=None, minute=None, score=None, model_probs=None):
    an=(standing or {}).get("analysis") or {}
    return {"ok": True, "version": "pipeline-1.0", "home": home, "away": away,
            "metrics": {"home": {"npxG_pg": None}, "away": {"npxG_pg": None}, "match_npxG": an.get("exp_total")},
            "context": {"weather": {"ok": False}, "travel": None, "referee": {"ok": False}},
            "live": ingest_live_events(live_events, minute, score) if live_events else empty_live(),
            "flags": ["PPDA yok"], "disclaimer": "npxG proxy / Understat ayrıntısı pipeline tam dosyada."}
def lines_from_pipeline(p):
    if not p: return []
    return [f"npxG maç {(p.get('metrics') or {}).get('match_npxG')}"]
