"""football-data.co.uk CSV + isteğe bağlı football-data.org.

Tahmine ek katman: lig 2.5 / KG tabanı + ev-dep son form.
Anahtar gerekmez (CSV). FOOTBALL_DATA_TOKEN varsa tablo yedeği.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
CACHE = ROOT / "data" / "fd_cache"
CACHE.mkdir(parents=True, exist_ok=True)
TTL = 12 * 3600

# 2025-26 sezon kodu football-data.co.uk: 2526
SEASON = os.environ.get("FD_CSV_SEASON", "2627")
SEASON_FALLBACK = "2526"
LEAGUE_FILES = {
    "E0": "İngiltere PL",
    "E1": "Championship",
    "SP1": "La Liga",
    "D1": "Bundesliga",
    "I1": "Serie A",
    "F1": "Ligue 1",
    "N1": "Eredivisie",
    "T1": "Süper Lig",
    "P1": "Portekiz",
    "B1": "Belçika",
}


import names


def _norm(s: str) -> str:
    return names.fold(s)


def _get(url: str, timeout=18) -> bytes:
    req = Request(url, headers={"User-Agent": "ATASU/5.4"})
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def _csv_path(code: str) -> Path:
    return CACHE / f"{SEASON}_{code}.csv"


def load_league(code: str) -> list[dict]:
    p = _csv_path(code)
    if p.exists() and time.time() - p.stat().st_mtime < TTL:
        raw = p.read_text(encoding="utf-8", errors="replace")
    else:
        urls = [
            f"https://www.football-data.co.uk/mmz4281/{SEASON}/{code}.csv",
            f"https://www.football-data.co.uk/mmz4281/{SEASON_FALLBACK}/{code}.csv",
        ]
        raw = ""
        try:
            for url in urls:
                try:
                    raw = _get(url).decode("latin-1", errors="replace")
                    if "HomeTeam" in raw or "FTHG" in raw:
                        break
                except Exception:
                    raw = ""
            if raw:
                p.write_text(raw, encoding="utf-8")
        except Exception:
            raw = ""
        if not raw:
            if p.exists():
                raw = p.read_text(encoding="utf-8", errors="replace")
            else:
                return []
    rows = []
    rdr = csv.DictReader(io.StringIO(raw))
    for row in rdr:
        h = (row.get("HomeTeam") or row.get("Home") or "").strip()
        a = (row.get("AwayTeam") or row.get("Away") or "").strip()
        fth = row.get("FTHG")
        fta = row.get("FTAG")
        if not h or fth in (None, ""):
            continue
        try:
            hg, ag = int(fth), int(fta)
        except Exception:
            continue
        tot = hg + ag
        rows.append({
            "league": code,
            "date": row.get("Date") or "",
            "home": h,
            "away": a,
            "hg": hg,
            "ag": ag,
            "tot": tot,
            "o25": tot >= 3,
            "btts": hg > 0 and ag > 0,
            "ms": "H" if hg > ag else ("A" if ag > hg else "D"),
            "b365h": _f(row.get("B365CH") or row.get("B365H")),
            "b365d": _f(row.get("B365CD") or row.get("B365D")),
            "b365a": _f(row.get("B365CA") or row.get("B365A")),
            "b365o25": _f(row.get("B365C>2.5") or row.get("B365>2.5") or row.get("BbAv>2.5")),
            "b365u25": _f(row.get("B365C<2.5") or row.get("B365<2.5")),
            "open_h": _f(row.get("B365H")),
            "open_d": _f(row.get("B365D")),
            "open_a": _f(row.get("B365A")),
            "open_o25": _f(row.get("B365>2.5")),
            "open_u25": _f(row.get("B365<2.5")),
            "hh": _i(row.get("HTHG")),
            "ha": _i(row.get("HTAG")),
        })
    return rows


def _i(v):
    try:
        if v in (None, ""):
            return None
        return int(float(str(v).replace(",", ".")))
    except Exception:
        return None


def _f(v):
    try:
        x = float(str(v).replace(",", "."))
        return x if x > 1 else None
    except Exception:
        return None


def _all_rows() -> list[dict]:
    out = []
    for code in LEAGUE_FILES:
        out.extend(load_league(code))
    return out


def _score_name(q: str, name: str) -> float:
    return names.score(q, name)


def lookup(home: str, away: str, league: str = "") -> dict:
    """Lig tabanı + iki takımın sezon formunu CSV'den çıkar."""
    empty = {"ok": False, "source": "football-data.co.uk", "note": ""}
    if not home and not away:
        empty["note"] = "takım yok"
        return empty
    rows = _all_rows()
    if not rows:
        empty["note"] = "CSV alınamadı"
        return empty

    def best_side(q, key):
        best, sc = None, 0.0
        seen = {}
        for r in rows:
            n = r[key]
            if n in seen:
                continue
            seen[n] = 1
            s = _score_name(q, n)
            if s > sc:
                sc, best = s, n
        return best, sc

    hn, hs = best_side(home, "home") if home else (None, 0)
    an, as_ = best_side(away, "away") if away else (None, 0)
    if hs < 0.45:
        hn, hs = best_side(home, "away") if home else (None, 0)
    if as_ < 0.45:
        an, as_ = best_side(away, "home") if away else (None, 0)

    team_rows_h = [r for r in rows if r["home"] == hn or r["away"] == hn] if hn and hs >= 0.45 else []
    team_rows_a = [r for r in rows if r["home"] == an or r["away"] == an] if an and as_ >= 0.45 else []
    codes = [r["league"] for r in team_rows_h + team_rows_a]
    code = max(set(codes), key=codes.count) if codes else None
    lig_rows = [r for r in rows if r["league"] == code] if code else rows

    def rate(rs, pred):
        if not rs:
            return None
        return round(100.0 * sum(1 for r in rs if pred(r)) / len(rs), 1)

    def side_form(name, rs):
        if not name or not rs:
            return None
        last = rs[-8:]
        gf = ga = 0
        for r in last:
            if r["home"] == name:
                gf += r["hg"]; ga += r["ag"]
            else:
                gf += r["ag"]; ga += r["hg"]
        n = len(last)
        return {
            "name": name,
            "n": n,
            "gf_pg": round(gf / n, 2) if n else None,
            "ga_pg": round(ga / n, 2) if n else None,
            "o25": rate(last, lambda r: r["o25"]),
            "btts": rate(last, lambda r: r["btts"]),
        }

    lig_o25 = rate(lig_rows, lambda r: r["o25"])
    lig_kg = rate(lig_rows, lambda r: r["btts"])
    hf = side_form(hn, team_rows_h)
    af = side_form(an, team_rows_a)
    combo_o25 = None
    combo_kg = None
    if hf and af and hf.get("o25") is not None and af.get("o25") is not None:
        combo_o25 = round(0.5 * hf["o25"] + 0.5 * af["o25"], 1)
    if hf and af and hf.get("btts") is not None and af.get("btts") is not None:
        combo_kg = round(0.5 * hf["btts"] + 0.5 * af["btts"], 1)

    ok = bool(lig_o25 is not None or hf or af)
    return {
        "ok": ok,
        "source": "football-data.co.uk",
        "season": SEASON,
        "league_code": code,
        "league_name": LEAGUE_FILES.get(code or "", code),
        "home_match": hn,
        "away_match": an,
        "home_score": round(hs, 2),
        "away_score": round(as_, 2),
        "sample_league": len(lig_rows),
        "league_o25": lig_o25,
        "league_kg": lig_kg,
        "home_form": hf,
        "away_form": af,
        "combo_o25": combo_o25,
        "combo_kg": combo_kg,
        "note": "" if ok else "isim eşleşmedi",
    }


def org_standings(competition="PL") -> dict | None:
    tok = os.environ.get("FOOTBALL_DATA_TOKEN") or os.environ.get("FD_TOKEN")
    if not tok:
        return None
    p = CACHE / f"org_{competition}.json"
    if p.exists() and time.time() - p.stat().st_mtime < TTL:
        return json.loads(p.read_text(encoding="utf-8"))
    try:
        req = Request(
            f"https://api.football-data.org/v4/competitions/{competition}/standings",
            headers={"X-Auth-Token": tok, "User-Agent": "ATASU/5.4"},
        )
        with urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode("utf-8"))
        p.write_text(json.dumps(data), encoding="utf-8")
        return data
    except Exception:
        return None
