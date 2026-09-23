"""Maçkolik Puan Durumu / Form / Alt-Üst / KG — resmi olmayan arşiv uçları."""
from __future__ import annotations

import json
import re
import time
from html import unescape
from urllib.parse import quote
from urllib.request import Request, urlopen

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
    "Accept": "application/json,text/javascript,text/html;q=0.9,*/*;q=0.8",
}

CUP_HINT = re.compile(
    r"kupa|cup|trophy|hazirlik|hazırlık|play.?off|eleme|qualif|friendly|turu|tur\b",
    re.I,
)

_CACHE: dict[str, tuple[float, object]] = {}
TTL = 25 * 60


def _cache_get(key):
    hit = _CACHE.get(key)
    if not hit:
        return None
    ts, val = hit
    if time.time() - ts > TTL:
        _CACHE.pop(key, None)
        return None
    return val


def _cache_set(key, val):
    _CACHE[key] = (time.time(), val)
    return val


def _fetch(url, limit=1_500_000, timeout=12):
    r = Request(url, headers=UA)
    with urlopen(r, timeout=timeout) as f:
        data = f.read(limit)
        ctype = f.headers.get_content_charset() or "utf-8"
    return data.decode(ctype, errors="replace")


def _fold(s: str) -> str:
    s = (s or "").casefold()
    table = str.maketrans("ıİiIâäöüûçşğ", "iiiiiaouucsg")
    s = s.translate(str.maketrans({
        "ı": "i", "i": "i", "İ": "i", "I": "i",
        "ö": "o", "ü": "u", "ş": "s", "ç": "c", "ğ": "g",
        "â": "a", "û": "u", "ä": "a",
    }))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(s: str) -> set[str]:
    stop = {"fc", "sk", "fk", "cf", "afc", "sc", "club", "spor", "sporlari", "the", "de", "fk"}
    return {t for t in _fold(s).split() if len(t) > 1 and t not in stop}


def _name_score(query: str, cand: str) -> float:
    q, c = _fold(query), _fold(cand)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if q in c or c in q:
        return 0.86
    qt, ct = _tokens(query), _tokens(cand)
    if not qt or not ct:
        return 0.0
    inter = len(qt & ct)
    return inter / max(len(qt), len(ct))


def search_team(name: str) -> list[dict]:
    q = (name or "").strip()
    if len(q) < 3:
        return []
    key = "search:" + _fold(q)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    url = "https://arsiv.mackolik.com/AjaxHandlers/SearchHandler.aspx?q=" + quote(q)
    try:
        raw = _fetch(url, limit=200000)
    except Exception:
        return _cache_set(key, [])
    out = []
    for m in re.finditer(
        r"text:'((?:\\'|[^'])*)'.*?desc:'((?:\\'|[^'])*)'.*?url:'([^']+)'",
        raw,
    ):
        text, desc, href = m.group(1), m.group(2), m.group(3)
        if "Takim/" not in href and "/Takim/" not in href:
            continue
        tm = re.search(r"/Takim/(\d+)", href)
        if not tm:
            continue
        out.append({
            "id": int(tm.group(1)),
            "name": text.replace("\\'", "'"),
            "desc": desc.replace("\\'", "'"),
            "url": ("https:" + href) if href.startswith("//") else href,
            "score": _name_score(q, text),
        })
    out.sort(key=lambda x: -x["score"])
    return _cache_set(key, out[:8])


def team_seasons(team_id: int, team_url: str = "") -> list[dict]:
    key = f"team:{team_id}"
    hit = _cache_get(key)
    if hit is not None:
        return hit
    url = team_url or f"https://arsiv.mackolik.com/Takim/{team_id}/x"
    try:
        html = _fetch(url, limit=800000)
    except Exception:
        return _cache_set(key, [])
    seen = set()
    rows = []
    for m in re.finditer(r"Puan-Durumu/s=(\d+)/([^\"'\s<]+)", html):
        sid, slug = m.group(1), unescape(m.group(2))
        if sid in seen:
            continue
        seen.add(sid)
        label = slug.replace("-", " ")
        rows.append({
            "season_id": int(sid),
            "slug": slug,
            "label": label,
            "cup": bool(CUP_HINT.search(label)),
        })
    return _cache_set(key, rows)


def _parse_standing_row(row, pos: int) -> dict:
    # [id, name, hP, aP, hW, aW, hD, aD, hL, aL, hGF, aGF, hGA, aGA, hPts, aPts, ...]
    def n(i, default=0):
        try:
            return int(row[i])
        except Exception:
            return default

    hp, ap = n(2), n(3)
    hw, aw = n(4), n(5)
    hd, ad = n(6), n(7)
    hl, al = n(8), n(9)
    hgf, agf = n(10), n(11)
    hga, aga = n(12), n(13)
    hpts, apts = n(14), n(15)
    played = hp + ap
    gf, ga = hgf + agf, hga + aga
    return {
        "pos": pos,
        "team_id": n(0),
        "name": str(row[1]) if len(row) > 1 else "",
        "played": played,
        "w": hw + aw,
        "d": hd + ad,
        "l": hl + al,
        "gf": gf,
        "ga": ga,
        "gd": gf - ga,
        "pts": hpts + apts,
        "home": {"p": hp, "w": hw, "d": hd, "l": hl, "gf": hgf, "ga": hga, "pts": hpts},
        "away": {"p": ap, "w": aw, "d": ad, "l": al, "gf": agf, "ga": aga, "pts": apts},
        "ppg": round((hpts + apts) / played, 2) if played else None,
        "avg_for": round(gf / played, 2) if played else None,
        "avg_against": round(ga / played, 2) if played else None,
    }


def fetch_standing(season_id: int) -> dict | None:
    key = f"st:{season_id}"
    hit = _cache_get(key)
    if hit is not None:
        return hit
    url = f"https://arsiv.mackolik.com/AjaxHandlers/StandingHandler.ashx?op=standing&id={season_id}"
    try:
        raw = _fetch(url)
        data = json.loads(raw)
    except Exception:
        return _cache_set(key, None)
    rows = []
    for i, row in enumerate(data.get("s") or [], 1):
        if not isinstance(row, list) or len(row) < 6:
            continue
        rows.append(_parse_standing_row(row, i))
    results = []
    for r in data.get("r") or []:
        # [id, date, status, homeId, awayId, code, hg, ag, "x - y", ?, h,d,a, ...]
        if not isinstance(r, list) or len(r) < 9:
            continue
        results.append({
            "date": r[1],
            "status": r[2],
            "home_id": r[3],
            "away_id": r[4],
            "hh": r[6] if len(r) > 6 else None,
            "ha": r[7] if len(r) > 7 else None,
            "hg": r[6] if False else None,
            "ft_raw": r[8],
            "ft": str(r[8]).replace(" ", ""),
            "h": r[10] if len(r) > 10 else None,
            "d": r[11] if len(r) > 11 else None,
            "a": r[12] if len(r) > 12 else None,
            "o25": r[16] if len(r) > 16 else None,
            "u25": r[17] if len(r) > 17 else None,
            "raw": r,
        })
    fixture = []
    for f in data.get("f") or []:
        if not isinstance(f, list) or len(f) < 5:
            continue
        fixture.append({"date": f[1], "time": f[2], "home_id": f[3], "away_id": f[4]})
    out = {
        "season_id": data.get("id") or season_id,
        "table": rows,
        "results": results[:30],
        "fixture": fixture[:20],
        "names": {r["team_id"]: r["name"] for r in rows},
    }
    return _cache_set(key, out)


def _decode_form(code: str) -> str:
    return "".join({"3": "W", "1": "D", "0": "L"}.get(ch, "") for ch in str(code or ""))


def fetch_form(season_id: int) -> dict[int, dict]:
    key = f"form:{season_id}"
    hit = _cache_get(key)
    if hit is not None:
        return hit
    url = f"https://arsiv.mackolik.com/Standings/Data/FormData.aspx?id={season_id}"
    try:
        data = json.loads(_fetch(url))
    except Exception:
        return _cache_set(key, {})
    out = {}
    for row in data or []:
        tid = int(row[0])
        out[tid] = {
            "all": _decode_form(row[1]),
            "home": _decode_form(row[2]),
            "away": _decode_form(row[3]),
            "played": row[4],
            "pts": row[5],
        }
    return _cache_set(key, out)


def fetch_uo(season_id: int) -> dict[int, dict]:
    key = f"uo:{season_id}"
    hit = _cache_get(key)
    if hit is not None:
        return hit
    url = f"https://arsiv.mackolik.com/Standings/Data/UnderOverData.aspx?id={season_id}"
    try:
        data = json.loads(_fetch(url))
    except Exception:
        return _cache_set(key, {})
    out = {}
    for row in data or []:
        tid = int(row[0])
        alt, ust = int(row[2] or 0), int(row[3] or 0)
        n = alt + ust
        out[tid] = {
            "alt": alt,
            "ust": ust,
            "n": n,
            "ust_pct": round(100 * ust / n, 1) if n else None,
            "seq": str(row[4] or ""),
            "home_alt": int(row[5] or 0),
            "home_ust": int(row[6] or 0),
            "away_alt": int(row[8] or 0),
            "away_ust": int(row[9] or 0),
        }
    return _cache_set(key, out)


def fetch_kg(season_id: int) -> dict[int, dict]:
    key = f"kg:{season_id}"
    hit = _cache_get(key)
    if hit is not None:
        return hit
    url = f"https://arsiv.mackolik.com/Standings/Data/KGData.aspx?id={season_id}"
    try:
        data = json.loads(_fetch(url))
    except Exception:
        return _cache_set(key, {})
    out = {}
    for row in data or []:
        tid = int(row[0])
        var, yok = int(row[2] or 0), int(row[3] or 0)
        n = var + yok
        out[tid] = {
            "var": var,
            "yok": yok,
            "n": n,
            "var_pct": round(100 * var / n, 1) if n else None,
            "seq": str(row[4] or ""),
            "home_var": int(row[5] or 0),
            "home_yok": int(row[6] or 0),
            "away_var": int(row[8] or 0),
            "away_yok": int(row[9] or 0),
        }
    return _cache_set(key, out)


def fetch_iyms(season_id: int) -> dict[int, dict]:
    """İY/MS 1-0-2 sayaçları (iç / dış)."""
    key = f"iyms:{season_id}"
    hit = _cache_get(key)
    if hit is not None:
        return hit
    url = f"https://arsiv.mackolik.com/Standings/Data/MatchResultData.aspx?id={season_id}"
    try:
        data = json.loads(_fetch(url))
    except Exception:
        return _cache_set(key, {})
    labels = ["1/1", "1/0", "1/2", "0/1", "0/0", "0/2", "2/1", "2/0", "2/2"]
    out = {}
    for row in data or []:
        tid = int(row[0])
        home = {lab: int(row[4 + i] or 0) for i, lab in enumerate(labels)}
        away = {lab: int(row[13 + i] or 0) for i, lab in enumerate(labels) if 13 + i < len(row)}
        def pack(d):
            n = sum(d.values())
            iy1 = d.get("1/1", 0) + d.get("1/0", 0) + d.get("1/2", 0)
            ms1 = d.get("1/1", 0) + d.get("0/1", 0) + d.get("2/1", 0)
            msx = d.get("1/0", 0) + d.get("0/0", 0) + d.get("2/0", 0)
            comeback = d.get("2/1", 0) + d.get("0/1", 0)  # İY geride/berabere bitiş ev
            collapse = d.get("1/0", 0) + d.get("1/2", 0)
            return {
                "n": n,
                "iy1_pct": round(100 * iy1 / n, 1) if n else None,
                "ms1_pct": round(100 * ms1 / n, 1) if n else None,
                "msx_pct": round(100 * msx / n, 1) if n else None,
                "lead_lost": collapse,
                "from_behind": comeback,
                "raw": d,
            }
        out[tid] = {"played": int(row[1] or 0), "pts": int(row[2] or 0), "home": pack(home), "away": pack(away)}
    return _cache_set(key, out)


def fetch_opta(season_id: int) -> dict[int, dict]:
    key = f"opta:{season_id}"
    hit = _cache_get(key)
    if hit is not None:
        return hit
    url = (
        "https://arsiv.mackolik.com/Standings/Statistics/LeagueTeamStatsData.aspx"
        f"?seasonId={season_id}&sortEnum=0&sortDir=0"
    )
    try:
        raw = _fetch(url)
        data = json.loads(raw)
    except Exception:
        return _cache_set(key, {})
    if isinstance(data, dict):
        data = data.get("data") or data.get("list") or []
    out = {}
    for row in data or []:
        if not isinstance(row, dict):
            continue
        team = row.get("team") or {}
        tid = team.get("id")
        if tid is None:
            continue
        gp = float(row.get("gamesPlayed") or 0) or 1.0
        sot = float(row.get("shotsOnTarget") or 0)
        soff = float(row.get("shotsOffTarget") or 0)
        shots = sot + soff
        succ = float(row.get("totalSuccPasses") or 0)
        uns = float(row.get("totalUnsuccPasses") or 0)
        out[int(tid)] = {
            "name": team.get("name"),
            "gp": int(row.get("gamesPlayed") or 0),
            "possession": row.get("possessionPercentage"),
            "pass_pct": round(100 * succ / (succ + uns), 1) if succ + uns else row.get("passAcc"),
            "shots_pg": round(shots / gp, 2),
            "sot_pg": round(sot / gp, 2),
            "corners_pg": round(float(row.get("cornersTaken") or 0) / gp, 2),
            "key_passes_pg": round(float(row.get("keyPasses") or 0) / gp, 2),
            "clean_sheets": int(row.get("cleanSheets") or 0),
            "goals": int(row.get("goals") or 0),
            "conceded": int(row.get("goalsConceded") or 0),
            "fouls_pg": round(float(row.get("totalFoulsConceded") or 0) / gp, 2),
            "yellow": int(row.get("yellowCards") or 0),
            "red": int(row.get("totalRedCards") or 0),
        }
    return _cache_set(key, out)


def _div(a, b):
    try:
        return a / b if b else None
    except Exception:
        return None


def _team_recent(results: list[dict], names: dict, tid: int, limit: int = 6) -> list[dict]:
    out = []
    for r in results:
        if r.get("home_id") != tid and r.get("away_id") != tid:
            continue
        ft = str(r.get("ft") or "")
        m = re.fullmatch(r"(\d+)-(\d+)", ft)
        if not m:
            continue
        hg, ag = int(m.group(1)), int(m.group(2))
        home = r.get("home_id") == tid
        gf, ga = (hg, ag) if home else (ag, hg)
        if gf > ga:
            letter = "W"
        elif gf == ga:
            letter = "D"
        else:
            letter = "L"
        opp_id = r.get("away_id") if home else r.get("home_id")
        out.append({
            "date": r.get("date"),
            "opp": names.get(opp_id, str(opp_id)),
            "ha": "H" if home else "A",
            "ft": ft,
            "gf": gf,
            "ga": ga,
            "res": letter,
            "total": hg + ag,
            "btts": hg > 0 and ag > 0,
        })
        if len(out) >= limit:
            break
    return out


def build_analysis(st: dict, home_row: dict | None, away_row: dict | None,
                   form: dict, uo: dict, kg: dict, iyms: dict, opta: dict) -> dict:
    table = st.get("table") or []
    n_teams = len(table) or 1
    gp = sum(t["played"] for t in table) or 1
    lg_gf = sum(t["gf"] for t in table)
    lg_avg = lg_gf / gp  # goals per team per match ≈ half of match total
    match_avg = (2 * lg_gf / gp) if gp else None  # wait gf is already team goals; sum of gf = all goals in league counted once per team... 
    # each match contributes to two teams' gf? No: sum(gf) = total goals scored in league (each goal once).
    # matches ≈ gp/2
    matches = gp / 2.0
    league_goals_pg = (lg_gf / matches) if matches else None

    def side_rates(row, loc):
        locd = row.get(loc) or {}
        p = locd.get("p") or 0
        return {
            "gf": _div(locd.get("gf") or 0, p),
            "ga": _div(locd.get("ga") or 0, p),
            "pts": _div(locd.get("pts") or 0, p),
            "p": p,
        }

    hr, ar = home_row, away_row
    h_home = side_rates(hr, "home") if hr else {}
    a_away = side_rates(ar, "away") if ar else {}
    exp_h = None
    exp_a = None
    if h_home.get("gf") is not None and a_away.get("ga") is not None:
        exp_h = round((h_home["gf"] + a_away["ga"]) / 2, 2)
    if a_away.get("gf") is not None and h_home.get("ga") is not None:
        exp_a = round((a_away["gf"] + h_home["ga"]) / 2, 2)
    exp_tot = round((exp_h or 0) + (exp_a or 0), 2) if (exp_h is not None and exp_a is not None) else None

    hid = hr["team_id"] if hr else None
    aid = ar["team_id"] if ar else None
    huo, auo = (uo.get(hid) if hid else None) or {}, (uo.get(aid) if aid else None) or {}
    hkg, akg = (kg.get(hid) if hid else None) or {}, (kg.get(aid) if aid else None) or {}

    def loc_uo(block, loc):
        if not block:
            return None
        if loc == "home":
            a, u = block.get("home_alt") or 0, block.get("home_ust") or 0
        else:
            a, u = block.get("away_alt") or 0, block.get("away_ust") or 0
        n = a + u
        return {"alt": a, "ust": u, "n": n, "ust_pct": round(100 * u / n, 1) if n else None}

    def loc_kg(block, loc):
        if not block:
            return None
        if loc == "home":
            v, y = block.get("home_var") or 0, block.get("home_yok") or 0
        else:
            v, y = block.get("away_var") or 0, block.get("away_yok") or 0
        n = v + y
        return {"var": v, "yok": y, "n": n, "var_pct": round(100 * v / n, 1) if n else None}

    h_uo_h = loc_uo(huo, "home")
    a_uo_a = loc_uo(auo, "away")
    h_kg_h = loc_kg(hkg, "home")
    a_kg_a = loc_kg(akg, "away")

    combo_o25 = None
    if h_uo_h and a_uo_a and h_uo_h.get("ust_pct") is not None and a_uo_a.get("ust_pct") is not None:
        combo_o25 = round(0.5 * h_uo_h["ust_pct"] + 0.5 * a_uo_a["ust_pct"], 1)
    combo_kg = None
    if h_kg_h and a_kg_a and h_kg_h.get("var_pct") is not None and a_kg_a.get("var_pct") is not None:
        combo_kg = round(0.5 * h_kg_h["var_pct"] + 0.5 * a_kg_a["var_pct"], 1)

    names = st.get("names") or {}
    h_recent = _team_recent(st.get("results") or [], names, hid) if hid else []
    a_recent = _team_recent(st.get("results") or [], names, aid) if aid else []
    h2h = []
    if hid and aid:
        for r in st.get("results") or []:
            ids = {r.get("home_id"), r.get("away_id")}
            if hid in ids and aid in ids:
                h2h.append(r)

    hop, aop = (opta.get(hid) if hid else None), (opta.get(aid) if aid else None)
    him, aim = (iyms.get(hid) if hid else None), (iyms.get(aid) if aid else None)

    gap = None
    if hr and ar:
        gap = hr["pts"] - ar["pts"]

    flags = []
    if exp_tot is not None and exp_tot >= 3.0:
        flags.append("tempo yüksek (tablo λ)")
    elif exp_tot is not None and exp_tot <= 2.15:
        flags.append("tempo düşük (tablo λ)")
    if combo_o25 is not None and combo_o25 >= 65:
        flags.append("taraf 2.5Ü sık")
    elif combo_o25 is not None and combo_o25 <= 40:
        flags.append("taraf 2.5Ü seyrek")
    if combo_kg is not None and combo_kg >= 60:
        flags.append("taraf KG sık")
    elif combo_kg is not None and combo_kg <= 35:
        flags.append("taraf tek kapı")
    if hr and hr.get("played", 0) < 6:
        flags.append("lig örnek küçük")
    if hop and aop:
        if (hop.get("sot_pg") or 0) >= 5 and (aop.get("sot_pg") or 0) >= 4:
            flags.append("iki taraf da şutlu")
        if (hop.get("clean_sheets") or 0) >= 3 and (aop.get("sot_pg") or 0) < 3:
            flags.append("ev kalesi sağlam / dep az isabet")

    return {
        "league_goals_pg": round(league_goals_pg, 2) if league_goals_pg else None,
        "n_teams": n_teams,
        "exp_home": exp_h,
        "exp_away": exp_a,
        "exp_total": exp_tot,
        "pts_gap": gap,
        "home_home": h_home,
        "away_away": a_away,
        "combo_o25": combo_o25,
        "combo_kg": combo_kg,
        "home_uo_home": h_uo_h,
        "away_uo_away": a_uo_a,
        "home_kg_home": h_kg_h,
        "away_kg_away": a_kg_a,
        "home_recent": h_recent,
        "away_recent": a_recent,
        "h2h": h2h[:5],
        "home_opta": hop,
        "away_opta": aop,
        "home_iyms": him,
        "away_iyms": aim,
        "flags": flags,
    }


def analysis_lines(pack: dict) -> list[str]:
    a = (pack or {}).get("analysis") or {}
    if not a:
        return []
    lines = []
    bits = []
    if a.get("league_goals_pg") is not None:
        bits.append(f"lig ort {a['league_goals_pg']} gol/maç")
    if a.get("exp_total") is not None:
        bits.append(f"eşleşme λ {a['exp_home']}+{a['exp_away']}={a['exp_total']}")
    if a.get("pts_gap") is not None:
        bits.append(f"puan farkı {a['pts_gap']:+d}")
    if bits:
        lines.append(" · ".join(bits))
    if a.get("combo_o25") is not None:
        hu, au = a.get("home_uo_home") or {}, a.get("away_uo_away") or {}
        lines.append(
            f"Taraf 2.5Ü: ev-iç %{hu.get('ust_pct')} ({hu.get('ust')}/{hu.get('n')}) · "
            f"dep-dış %{au.get('ust_pct')} ({au.get('ust')}/{au.get('n')}) · karışık %{a['combo_o25']}"
        )
    if a.get("combo_kg") is not None:
        hk, ak = a.get("home_kg_home") or {}, a.get("away_kg_away") or {}
        lines.append(
            f"Taraf KG: ev-iç %{hk.get('var_pct')} · dep-dış %{ak.get('var_pct')} · karışık %{a['combo_kg']}"
        )
    hop, aop = a.get("home_opta") or {}, a.get("away_opta") or {}
    if hop or aop:
        def opt(x, tag):
            if not x:
                return None
            return (
                f"{tag} TSO %{x.get('possession')} · şut {x.get('shots_pg')} · isabet {x.get('sot_pg')} · "
                f"korner {x.get('corners_pg')} · CS {x.get('clean_sheets')}"
            )
        if opt(hop, "ev"):
            lines.append(opt(hop, "ev"))
        if opt(aop, "dep"):
            lines.append(opt(aop, "dep"))
    him = ((a.get("home_iyms") or {}).get("home") or {})
    if him.get("n"):
        lines.append(
            f"Ev iç saha İY/MS: İY1 %{him.get('iy1_pct')} · MS1 %{him.get('ms1_pct')} · "
            f"önde kayıp {him.get('lead_lost')} · geriden {him.get('from_behind')}"
        )
    def rec(tag, rows):
        if not rows:
            return None
        s = " ".join(f"{x['res']}{x['ft']}({x['ha'][0]})" for x in rows[:5])
        o25 = sum(1 for x in rows if x["total"] >= 3)
        return f"{tag} son {len(rows)}: {s} · 2.5Ü {o25}/{len(rows)}"
    if rec("Ev", a.get("home_recent") or []):
        lines.append(rec("Ev", a.get("home_recent") or []))
    if rec("Dep", a.get("away_recent") or []):
        lines.append(rec("Dep", a.get("away_recent") or []))
    if a.get("flags"):
        lines.append("okuma: " + " · ".join(a["flags"]))
    return lines


def _pick_season(home_ss: list[dict], away_ss: list[dict]) -> dict | None:
    hids = {s["season_id"]: s for s in home_ss}
    aids = {s["season_id"]: s for s in away_ss}
    common = [hids[i] for i in hids if i in aids]
    common_league = [s for s in common if not s.get("cup")]
    home_league = [s for s in home_ss if not s.get("cup")]
    away_league = [s for s in away_ss if not s.get("cup")]
    for pool in (common_league, home_league, away_league, common, home_ss, away_ss):
        if pool:
            return pool[0]
    return None


def _find_row(table: list[dict], team_id: int | None, name: str) -> dict | None:
    if team_id:
        for r in table:
            if r["team_id"] == team_id:
                return r
    best, sc = None, 0.55
    for r in table:
        s = _name_score(name, r["name"])
        if s > sc:
            best, sc = r, s
    return best


def resolve_match(home: str, away: str, league: str = "") -> dict:
    """Bülten/maç adından lig tablosu + form + alt/üst + KG."""
    out = {
        "ok": False,
        "home": home,
        "away": away,
        "league_query": league,
        "season_id": None,
        "season_label": None,
        "source": "arsiv.mackolik.com/Puan-Durumu",
        "home_row": None,
        "away_row": None,
        "home_form": None,
        "away_form": None,
        "home_uo": None,
        "away_uo": None,
        "home_kg": None,
        "away_kg": None,
        "table_preview": [],
        "note": "",
    }
    if not home and not away:
        out["note"] = "Takım adı yok."
        return out

    hs = search_team(home) if home else []
    aws = search_team(away) if away else []
    hbest = hs[0] if hs and hs[0]["score"] >= 0.45 else None
    abest = aws[0] if aws and aws[0]["score"] >= 0.45 else None
    out["home_hit"] = hbest
    out["away_hit"] = abest

    hseasons = team_seasons(hbest["id"], hbest.get("url")) if hbest else []
    aseasons = team_seasons(abest["id"], abest.get("url")) if abest else []
    season = _pick_season(hseasons, aseasons)
    if not season:
        out["note"] = "Maçkolik puan durumu sezonu bulunamadı."
        return out

    st = fetch_standing(season["season_id"])
    if not st or not st.get("table"):
        out["note"] = "Puan tablosu boş döndü."
        return out

    sid = season["season_id"]
    form = fetch_form(sid)
    uo = fetch_uo(sid)
    kg = fetch_kg(sid)
    iyms = fetch_iyms(sid)
    opta = fetch_opta(sid)

    hrow = _find_row(st["table"], hbest["id"] if hbest else None, home or "")
    arow = _find_row(st["table"], abest["id"] if abest else None, away or "")

    def attach(row):
        if not row:
            return None
        tid = row["team_id"]
        return {
            **row,
            "form": form.get(tid),
            "uo": uo.get(tid),
            "kg": kg.get(tid),
            "iyms": iyms.get(tid),
            "opta": opta.get(tid),
        }

    analysis = build_analysis(st, hrow, arow, form, uo, kg, iyms, opta)
    out.update({
        "ok": True,
        "season_id": sid,
        "season_label": season.get("label"),
        "home_row": attach(hrow),
        "away_row": attach(arow),
        "home_form": form.get(hrow["team_id"]) if hrow else None,
        "away_form": form.get(arow["team_id"]) if arow else None,
        "home_uo": uo.get(hrow["team_id"]) if hrow else None,
        "away_uo": uo.get(arow["team_id"]) if arow else None,
        "home_kg": kg.get(hrow["team_id"]) if hrow else None,
        "away_kg": kg.get(arow["team_id"]) if arow else None,
        "analysis": analysis,
        "table_preview": [
            {"pos": r["pos"], "name": r["name"], "pts": r["pts"], "p": r["played"], "gd": r["gd"]}
            for r in st["table"][:8]
        ],
        "note": "Canlı Maçkolik arşiv tablosu + Opta/İY-MS. Resmi API değil.",
    })
    return out


def standing_lines(pack: dict, side: str = "home") -> list[str]:
    row = (pack or {}).get("home_row" if side == "home" else "away_row")
    if not row:
        return []
    bits = [
        f"{row['pos']}. {row['name']} {row['played']}O {row['w']}-{row['d']}-{row['l']} "
        f"{row['gf']}-{row['ga']} {row['pts']}p"
    ]
    loc = row["home"] if side == "home" else row["away"]
    tag = "iç saha" if side == "home" else "deplasman"
    bits.append(
        f"{tag} {loc['p']}O {loc['w']}-{loc['d']}-{loc['l']} {loc['gf']}-{loc['ga']} {loc['pts']}p"
    )
    fm = row.get("form") or {}
    key = "home" if side == "home" else "away"
    if fm.get("all"):
        bits.append(f"form {fm.get(key) or fm['all']} (genel {fm['all']})")
    uo = row.get("uo") or {}
    if uo.get("n"):
        if side == "home" and (uo.get("home_alt") + uo.get("home_ust")):
            n = uo["home_alt"] + uo["home_ust"]
            bits.append(f"iç saha 2.5Ü {uo['home_ust']}/{n}")
        elif side == "away" and (uo.get("away_alt") + uo.get("away_ust")):
            n = uo["away_alt"] + uo["away_ust"]
            bits.append(f"deplasman 2.5Ü {uo['away_ust']}/{n}")
        else:
            bits.append(f"2.5Ü {uo['ust']}/{uo['n']} (%{uo.get('ust_pct')})")
    kg = row.get("kg") or {}
    if kg.get("n"):
        bits.append(f"KG {kg['var']}/{kg['n']} (%{kg.get('var_pct')})")
    return bits


# İddaa'da gerçekten açık olan marketler — kapalı hatta yorum yok.
IDDAA_PICKS = [
    ("h", "MS 1", "MS 1"),
    ("d", "MS X", "MS X"),
    ("a", "MS 2", "MS 2"),
    ("o25", "2,5 Üst", "2,5 Üst"),
    ("u25", "2,5 Alt", "2,5 Alt"),
    ("o35", "3,5 Üst", "3,5 Üst"),
    ("u35", "3,5 Alt", "3,5 Alt"),
    ("btts", "KG Var", "KG Var"),
    ("nobtts", "KG Yok", "KG Yok"),
    ("iyo15", "İY 1,5 Üst", "İY 1,5 Üst"),
    ("iyu15", "İY 1,5 Alt", "İY 1,5 Alt"),
    ("g6", "6+ Gol", "6+ Gol"),
    ("g45", "4,5 Üst", "4,5 Üst"),
]


def open_markets(q: dict) -> list[tuple[str, str, float]]:
    out = []
    for key, label, stat in IDDAA_PICKS:
        v = q.get(key)
        if v is None:
            continue
        try:
            f = float(v)
        except Exception:
            continue
        if f > 1:
            out.append((key, label, f))
    return out


def score_open_picks(q: dict, stats_obj: dict | None, lh: dict | None, pack: dict | None) -> list[dict]:
    """Sadece bültende/linkte duran oranları puanla."""
    stats_obj = stats_obj or {}
    ranked = []
    model_map = {
        "h": "ms1", "d": "msx", "a": "ms2",
        "o25": "p_o25", "u25": "p_u25", "btts": "p_btts", "g6": "p_g6",
    }
    dc = (lh or {}).get("dixon_coles") or {}
    an = (pack or {}).get("analysis") or {}
    huo = ((pack or {}).get("home_row") or {}).get("uo") or {}
    auo = ((pack or {}).get("away_row") or {}).get("uo") or {}
    hkg = ((pack or {}).get("home_row") or {}).get("kg") or {}
    akg = ((pack or {}).get("away_row") or {}).get("kg") or {}
    combo_o25 = an.get("combo_o25")
    combo_kg = an.get("combo_kg")
    exp_tot = an.get("exp_total")
    exp_h, exp_a = an.get("exp_home"), an.get("exp_away")

    def implied(o):
        try:
            o = float(o)
            return 1.0 / o if o > 1 else None
        except Exception:
            return None

    for key, label, odd in open_markets(q):
        hist = stats_obj.get(label if label != "4,5 Üst" else "4,5 Üst")
        if key == "g45":
            hist = stats_obj.get("4,5 Üst")
        model_p = dc.get(model_map[key]) if key in model_map else None
        if key == "u25" and dc.get("p_u25") is None and dc.get("p_o25") is not None:
            model_p = round(100 - float(dc["p_o25"]), 1)
        book_p = implied(odd)
        book_pct = round(book_p * 100, 1) if book_p else None
        stand_boost = 0.0
        stand_note = ""
        if key == "o25":
            avg = combo_o25
            if avg is None:
                vals = [x.get("ust_pct") for x in (huo, auo) if x.get("ust_pct") is not None]
                avg = sum(vals) / len(vals) if vals else None
            if avg is not None:
                stand_boost = (avg - 50) * 0.28
                stand_note = f"taraf 2.5Ü %{avg:.0f}"
            if exp_tot is not None:
                stand_boost += (exp_tot - 2.55) * 4
                stand_note += f" · λ {exp_tot}"
        elif key == "u25":
            avg = combo_o25
            if avg is None:
                vals = [x.get("ust_pct") for x in (huo, auo) if x.get("ust_pct") is not None]
                avg = sum(vals) / len(vals) if vals else None
            if avg is not None:
                stand_boost = (50 - avg) * 0.28
                stand_note = f"taraf 2.5Ü %{avg:.0f}"
            if exp_tot is not None:
                stand_boost += (2.55 - exp_tot) * 4
                stand_note += f" · λ {exp_tot}"
        elif key == "o35":
            if exp_tot is not None:
                stand_boost = (exp_tot - 3.15) * 8
                stand_note = f"λ {exp_tot}"
        elif key == "u35":
            if exp_tot is not None:
                stand_boost = (3.15 - exp_tot) * 8
                stand_note = f"λ {exp_tot}"
        elif key == "btts":
            avg = combo_kg
            if avg is None:
                vals = [x.get("var_pct") for x in (hkg, akg) if x.get("var_pct") is not None]
                avg = sum(vals) / len(vals) if vals else None
            if avg is not None:
                stand_boost = (avg - 50) * 0.25
                stand_note = f"taraf KG %{avg:.0f}"
            if exp_h is not None and exp_a is not None and exp_h >= 1.15 and exp_a >= 1.05:
                stand_boost += 4
                stand_note += " · iki kapı λ"
        elif key == "nobtts":
            avg = combo_kg
            if avg is None:
                vals = [x.get("var_pct") for x in (hkg, akg) if x.get("var_pct") is not None]
                avg = sum(vals) / len(vals) if vals else None
            if avg is not None:
                stand_boost = (50 - avg) * 0.25
                stand_note = f"taraf KG %{avg:.0f}"
        elif key == "h" and exp_h is not None and exp_a is not None:
            stand_boost = (exp_h - exp_a) * 6
            stand_note = f"λ ev {exp_h} / dep {exp_a}"
        elif key == "a" and exp_h is not None and exp_a is not None:
            stand_boost = (exp_a - exp_h) * 6
            stand_note = f"λ ev {exp_h} / dep {exp_a}"

        p_use = None
        if isinstance(hist, (int, float)) and isinstance(model_p, (int, float)):
            p_use = 0.50 * float(hist) + 0.30 * float(model_p)
            if key in ("o25", "u25") and combo_o25 is not None:
                p_use += 0.20 * (combo_o25 if key == "o25" else 100 - combo_o25)
            elif key in ("btts", "nobtts") and combo_kg is not None:
                p_use += 0.20 * (combo_kg if key == "btts" else 100 - combo_kg)
            else:
                p_use = 0.55 * float(hist) + 0.45 * float(model_p)
        elif isinstance(hist, (int, float)):
            p_use = float(hist)
        elif isinstance(model_p, (int, float)):
            p_use = float(model_p)
        elif key == "o25" and combo_o25 is not None:
            p_use = combo_o25
        elif key == "u25" and combo_o25 is not None:
            p_use = 100 - combo_o25
        elif key == "btts" and combo_kg is not None:
            p_use = combo_kg
        elif key == "nobtts" and combo_kg is not None:
            p_use = 100 - combo_kg
        if p_use is not None:
            p_use = max(5.0, min(92.0, p_use + stand_boost))
        ev = None
        if p_use is not None and odd > 1:
            ev = round((p_use / 100.0) * odd - 1, 3)
        score = 0.0
        if ev is not None:
            score = ev * 100 + (4 if (hist or 0) >= 62 else 0)
        ranked.append({
            "key": key,
            "name": label,
            "odds": odd,
            "hist_percent": hist,
            "model_percent": model_p,
            "book_percent": book_pct,
            "blend_percent": round(p_use, 1) if p_use is not None else None,
            "ev": ev,
            "stand_note": stand_note,
            "score": round(score, 2),
        })
    ranked.sort(key=lambda x: (x["score"], x.get("blend_percent") or 0), reverse=True)
    return ranked


def _ima(odd):
    try:
        o = float(odd)
        return round(100.0 / o, 1) if o > 1 else None
    except Exception:
        return None


MIN_ODD = 1.30
MAX_ODD = 2.35
MIN_BLEND = 63.0
MIN_LAYER = 2


def _layers(x) -> int:
    n = 0
    if isinstance(x.get("hist_percent"), (int, float)) and x["hist_percent"] >= 58:
        n += 1
    if isinstance(x.get("model_percent"), (int, float)) and x["model_percent"] >= 58:
        n += 1
    if isinstance(x.get("blend_percent"), (int, float)) and x["blend_percent"] >= 62:
        n += 1
    return n


def tercih_from_open(ranked: list[dict], n_hist: int) -> list[str]:
    """Minimum kayıp: yalnızca 1.30–2.35 açık iddaa. 1.07–1.10 yok. Hiza yoksa GEÇ."""
    if not ranked:
        return ["Bültende açık iddaa oranı yok.", "KARAR: GEÇ"]
    band = []
    disi = []
    for x in ranked:
        try:
            o = float(x.get("odds") or 0)
        except Exception:
            continue
        if MIN_ODD <= o <= MAX_ODD:
            band.append(x)
        else:
            disi.append(x)
    band.sort(key=lambda x: (-_layers(x), -(x.get("blend_percent") or 0)))
    lines = [f"Kupon bandı {MIN_ODD}–{MAX_ODD}. 1.10'luk favori yok sayılır."]
    if disi:
        kisa = [f"{x['name']} {x['odds']}" for x in disi if float(x.get("odds") or 0) < MIN_ODD]
        if kisa:
            lines.append("Band dışı kısa (yok sayıldı): " + ", ".join(kisa[:4]) + ".")
    if not band:
        lines.append("Açık iddaada bu bantta iş yok.")
        lines.append("KARAR: GEÇ")
        return lines[:6]
    x = band[0]
    p = x.get("blend_percent")
    h = x.get("hist_percent")
    m = x.get("model_percent")
    lay = _layers(x)
    lines.append(
        f"Aday: {x['name']} {x['odds']} · kalıp %{h if h is not None else '-'} · "
        f"model %{m if m is not None else '-'} · birleşik %{p if p is not None else '-'} · hiza {lay}/3"
    )
    oyna = lay >= MIN_LAYER and (p or 0) >= MIN_BLEND and (n_hist or 0) >= 25
    if oyna:
        lines.append(f"KARAR: OYNA · {x['name']} {x['odds']} · tek iş · tek birim")
    else:
        lines.append("KARAR: GEÇ")
        if lay < MIN_LAYER:
            lines.append("Katmanlar aynı işte durmuyor.")
        elif (p or 0) < MIN_BLEND:
            lines.append(f"Birleşik %{(p or 0):.0f} < %{MIN_BLEND:.0f}.")
        elif (n_hist or 0) < 25:
            lines.append(f"Benzer maç {n_hist or 0}; örnek yetmez.")
    return lines[:7]
