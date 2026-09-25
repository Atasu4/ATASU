"""Understat xG (büyük 5) + Opta/proxy birleşimi. Yoksa sessiz düşer."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen

import names

ROOT = Path(__file__).parent
CACHE = ROOT / "data" / "xg_cache"
CACHE.mkdir(parents=True, exist_ok=True)
TTL = 12 * 3600

LEAGUES = {
    "epl": "EPL",
    "premier": "EPL",
    "ingiltere": "EPL",
    "la liga": "La_liga",
    "ispanya": "La_liga",
    "bundesliga": "Bundesliga",
    "almanya": "Bundesliga",
    "serie a": "Serie_A",
    "italya": "Serie_A",
    "ligue 1": "Ligue_1",
    "fransa": "Ligue_1",
}


def _guess_league(label: str) -> str | None:
    n = names.fold(label or "")
    for k, v in LEAGUES.items():
        if k in n:
            return v
    return None


def _get(url: str) -> str:
    req = Request(url, headers={"User-Agent": "ATASU/5.7"})
    with urlopen(req, timeout=12) as r:
        return r.read().decode("utf-8", "replace")


def _load_league(code: str, season: int) -> dict:
    path = CACHE / f"{code}_{season}.json"
    if path.exists() and time.time() - path.stat().st_mtime < TTL:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    html = ""
    try:
        html = _get(f"https://understat.com/league/{code}/{season}")
    except Exception:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}
    m = re.search(r"teamsData\s*=\s*JSON.parse\('(.*?)'\)", html)
    if not m:
        return {}
    raw = m.group(1).encode("utf-8").decode("unicode_escape")
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    out = {}
    for _tid, block in (data or {}).items():
        title = block.get("title") or ""
        hist = block.get("history") or []
        if not hist:
            continue
        n = len(hist)
        xg = sum(float(x.get("xG") or 0) for x in hist)
        xga = sum(float(x.get("xGA") or 0) for x in hist)
        npxg = sum(float(x.get("npxG") or x.get("xG") or 0) for x in hist)
        out[names.canon(title)] = {
            "name": title,
            "n": n,
            "xg_pg": round(xg / n, 3),
            "xga_pg": round(xga / n, 3),
            "npxg_pg": round(npxg / n, 3),
            "src": "understat",
        }
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def lookup(home: str, away: str, league: str = "", season: int = 2026) -> dict:
    code = _guess_league(league)
    empty = {"ok": False, "src": "understat", "note": "lig yok veya sayfa alınamadı"}
    if not code:
        empty["note"] = "Understat bu ligi kapsamıyor"
        return empty
    table = _load_league(code, season)
    if not table:
        return empty

    def hit(q):
        best, sc = None, 0.0
        for k, row in table.items():
            s = names.score(q, row.get("name") or k)
            if s > sc:
                sc, best = s, row
        return best if sc >= 0.62 else None

    h, a = hit(home), hit(away)
    if not h and not a:
        empty["note"] = "takım eşleşmedi"
        return empty
    nh = h["npxg_pg"] if h else None
    na = a["npxg_pg"] if a else None
    ha = h["xga_pg"] if h else None
    aa = a["xga_pg"] if a else None
    exp_h = round(0.55 * nh + 0.45 * (aa or nh), 2) if nh is not None else None
    exp_a = round(0.55 * na + 0.45 * (ha or na), 2) if na is not None else None
    tot = round((exp_h or 0) + (exp_a or 0), 2) if exp_h is not None and exp_a is not None else None
    return {
        "ok": True,
        "src": "understat",
        "league": code,
        "home": h,
        "away": a,
        "npxg_home": exp_h,
        "npxg_away": exp_a,
        "npxg_total": tot,
    }


def enrich(standing: dict | None, home: str, away: str, league: str = "") -> dict:
    """Standing analysis'e Understat yaz; varsa Opta resmi kalsın."""
    st = standing or {}
    an = st.setdefault("analysis", {})
    src = an.get("npxg_src") or ""
    if src == "opta" and an.get("npxg_total") is not None:
        an.setdefault("flags", []).append("npxG opta resmi")
        return st
    try:
        u = lookup(home, away, league or st.get("season_label") or "")
    except Exception as e:
        an.setdefault("flags", []).append("understat: " + str(e)[:40])
        return st
    if u.get("ok") and u.get("npxg_total") is not None:
        an["npxg_home"] = u["npxg_home"]
        an["npxg_away"] = u["npxg_away"]
        an["npxg_total"] = u["npxg_total"]
        an["npxg_src"] = "understat"
        an.setdefault("flags", []).append(f"npxG understat {u['npxg_total']}")
    return st
