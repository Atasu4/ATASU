"""Canlı 60-75 masası — pre-match fikri tempo bozulunca öldürür."""
from __future__ import annotations

import re


def parse_score(s) -> tuple[int, int] | None:
    m = re.search(r"(\d+)\s*[-–:]\s*(\d+)", str(s or ""))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def extract_from_text(text: str) -> dict:
    t = text or ""
    minute = None
    for rx in (r"(\d{1,3})\s*[+']\s*", r"dakika[^\d]{0,6}(\d{1,3})", r"'(\d{1,3})"):
        m = re.search(rx, t, re.I)
        if m:
            v = int(m.group(1))
            if 1 <= v <= 130:
                minute = v
                break
    sc = None
    m = re.search(r"(?:skor|score)[^\d]{0,8}(\d+)\s*[-–]\s*(\d+)", t, re.I)
    if m:
        sc = f"{m.group(1)}-{m.group(2)}"
    return {"minute": minute, "score": sc}


def read(minute=None, score=None, pick_key: str | None = None, pre_karar: str = "") -> dict:
    try:
        m = int(minute) if minute is not None else None
    except Exception:
        m = None
    ft = parse_score(score)
    hg = ag = tot = None
    if ft:
        hg, ag = ft
        tot = hg + ag
    window = m is not None and 60 <= m <= 75
    late = m is not None and m >= 80
    cancel = False
    idea = None
    if window and tot is not None:
        if pick_key == "o25" and tot >= 3:
            idea = "2.5Ü geldi; kuponu kovalama."
            cancel = True
        elif pick_key == "o25" and tot <= 1:
            idea = "Tempo düşük. Pre-match 2.5Ü fikri zayıfladı; late over ancak şut geliyorsa."
        elif pick_key == "u25" and tot >= 2:
            idea = "Alt fikri tehlikede."
            cancel = True
        elif pick_key == "h" and hg is not None and hg <= ag:
            idea = "Ev önde değil; MS1 pre-match fikrini bırak."
            cancel = True
        elif pick_key == "a" and ag is not None and ag <= hg:
            idea = "Dep önde değil; MS2 fikrini bırak."
            cancel = True
        elif pick_key == "btts" and hg and ag:
            idea = "KG geldi."
            cancel = True
        elif pick_key == "btts" and tot == 0:
            idea = "0-0, 60+. KG için iki kapı da hâlâ kapalı."
        else:
            idea = "60-75 pencere: ikinci yarı temposunu izle."
    elif late:
        idea = "80+. Yeni pre-match iş açma."
    elif m is None:
        idea = "Canlı dakika yok; pre-match fikir duruyor."
    else:
        idea = f"{m}. dakika, skor {score or '—'}."

    if pre_karar == "OYNA" and cancel:
        karar = "IPTAL"
    elif pre_karar == "OYNA" and window and idea and "zayıfladı" in idea:
        karar = "IZLE"
    else:
        karar = pre_karar or "IZLE"

    return {
        "ok": m is not None,
        "minute": m,
        "score": score,
        "hg": hg,
        "ag": ag,
        "tot": tot,
        "window_60_75": window,
        "late": late,
        "cancel": cancel,
        "karar": karar,
        "idea": idea,
        "note": idea,
    }
