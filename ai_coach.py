"""ATASU AI katmanı: sayısal motoru yorumcu metnine bırakır."""
from __future__ import annotations

import commentator


def compose(brief: dict | None = None, standing: dict | None = None) -> dict:
    brief = brief or {}
    pack = commentator.compose(
        brief=brief,
        standing=standing if standing is not None else brief.get("standing"),
        lh=brief.get("lh") or brief.get("lh_model"),
        stats_obj=brief.get("stats"),
        q=brief.get("odds") or {},
        title=brief.get("title") or "",
        n=brief.get("sample") or brief.get("matched") or 0,
        p6=brief.get("plus6"),
        news=(standing or brief.get("standing") or {}).get("news"),
        context=(standing or brief.get("standing") or {}).get("context"),
    )
    return {
        "ok": True,
        "engine": "atasu-coach",
        "llm": False,
        "stance": pack.get("stance"),
        "tercih_ref": pack.get("karar"),
        "headline": pack.get("headline"),
        "bullets": pack.get("why") or [],
        "text": pack.get("script"),
        "note": "Yorumcu tek ses. Kapılar içeride.",
    }
