from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from html import unescape
from pathlib import Path
from collections import Counter
import json, re

ROOT = Path(__file__).parent
HISTORY_FILE = ROOT / "data" / "history.json"
HISTORY = []
HISTORY_WARNING = None
if HISTORY_FILE.exists():
    HISTORY = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
else:
    HISTORY_WARNING = "data/history.json yok. Motorlar boş havuzla açıldı."

MARKETS = ["h", "d", "a", "u25", "o25", "btts", "nobtts", "u35", "o35", "iyu15", "iyo15", "g6", "g45", "g01", "g23"]
NAMES = {
    "h": "MS 1", "d": "MS X", "a": "MS 2",
    "u25": "2,5 Alt", "o25": "2,5 Üst",
    "btts": "KG Var", "nobtts": "KG Yok",
    "u35": "3,5 Alt", "o35": "3,5 Üst",
    "iyu15": "İY 1,5 Alt", "iyo15": "İY 1,5 Üst",
    "g6": "6+ Gol", "g45": "4-5 Gol Üst (~4,5 Üst)",
    "g01": "0-1 Gol", "g23": "2-3 Gol",
}
GROUPS = [
    ("1X2", ["h", "d", "a"]),
    ("2,5 Alt/Üst", ["u25", "o25"]),
    ("3,5 Alt/Üst", ["u35", "o35"]),
    ("Karşılıklı Gol", ["btts", "nobtts"]),
    ("İY 1,5 Alt/Üst", ["iyu15", "iyo15"]),
]
app = FastAPI(title="ATASU Intelligence", version="4.9.4")
WEIGHTS = {
    "h": 1.2, "d": 1.0, "a": 1.2,
    "u25": 1.1, "o25": 1.1,
    "u35": 0.8, "o35": 0.8,
    "btts": 0.9, "nobtts": 0.9,
    "iyu15": 0.6, "iyo15": 0.6,
    "g45": 0.7, "g6": 0.7, "g01": 0.4, "g23": 0.4,
}
if (ROOT / "static").exists():
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def score(v):
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(v or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def stats(rows):
    z = Counter(); scores = Counter(); n = nh = tg = hg_sum = ag_sum = 0
    for r in rows:
        ft = score(r.get("ft"))
        if not ft:
            continue
        n += 1; h, a = ft; t = h + a; tg += t; hg_sum += h; ag_sum += a
        scores[f"{h}-{a}"] += 1
        z["home" if h > a else "draw" if h == a else "away"] += 1
        z["o15" if t >= 2 else "u15"] += 1
        z["o25" if t >= 3 else "u25"] += 1
        z["o35" if t >= 4 else "u35"] += 1
        z["o45" if t >= 5 else "u45"] += 1
        z["g6" if t >= 6 else "ng6"] += 1
        z["btts" if h > 0 and a > 0 else "nobtts"] += 1
        ht = score(r.get("ht"))
        if ht:
            nh += 1; hh, ha = ht
            z["htHome" if hh > ha else "htDraw" if hh == ha else "htAway"] += 1
            fh = hh + ha; sh = t - fh
            z["fh" if fh > sh else "sh" if sh > fh else "eq"] += 1

    def p(k, d):
        return round(100 * z[k] / d, 1) if d else None

    return {
        "sample_ft": n, "sample_ht": nh,
        "avg_goals": round(tg / n, 2) if n else None,
        "avg_home_goals": round(hg_sum / n, 2) if n else None,
        "avg_away_goals": round(ag_sum / n, 2) if n else None,
        "top_scores": [{"score": s, "count": c, "percent": round(c / n * 100, 1)} for s, c in scores.most_common(6)] if n else [],
        "MS 1": p("home", n), "MS X": p("draw", n), "MS 2": p("away", n),
        "1,5 Üst": p("o15", n), "1,5 Alt": p("u15", n),
        "2,5 Üst": p("o25", n), "2,5 Alt": p("u25", n),
        "KG Var": p("btts", n), "KG Yok": p("nobtts", n),
        "3,5 Üst": p("o35", n), "3,5 Alt": p("u35", n),
        "4,5 Üst": p("o45", n), "6+ Gol": p("g6", n),
        "İY 1": p("htHome", nh), "İY X": p("htDraw", nh), "İY 2": p("htAway", nh),
        "Daha çok gol 1.Y": p("fh", nh), "Daha çok gol 2.Y": p("sh", nh), "Yarılar eşit": p("eq", nh),
    }


def probability_engine(q):
    groups = []
    for title, keys in GROUPS:
        if not all(k in q for k in keys):
            continue
        inv = [1 / q[k] for k in keys]
        book = sum(inv)
        if book < 1:
            groups.append({
                "market": title, "book_percent": round(book * 100, 2),
                "margin_percent": round((book - 1) * 100, 2), "valid": False,
                "warning": "Tutarsız tam market: toplam implied probability %100 altında.",
                "selections": [{"key": k, "name": NAMES[k], "odds": q[k], "raw_percent": round(100 / q[k], 2), "fair_percent": None} for k in keys],
            })
            continue
        fair = [x / book for x in inv]
        groups.append({
            "market": title, "book_percent": round(book * 100, 2),
            "margin_percent": round((book - 1) * 100, 2), "valid": True, "warning": None,
            "selections": [{"key": k, "name": NAMES[k], "odds": q[k], "raw_percent": round(100 / q[k], 2), "fair_percent": round(100 * f, 2)} for k, f in zip(keys, fair)],
        })
    return groups


def implied(o):
    try:
        o = float(o)
        return 1.0 / o if o > 1 else None
    except Exception:
        return None


def prob_gap(a, b):
    pa, pb = implied(a), implied(b)
    if pa is None or pb is None:
        return None
    return abs(pa - pb)


def match_rows(q, tol, league=""):
    pool = [r for r in HISTORY if score(r.get("ft")) is not None]
    if league.strip():
        pool = [r for r in pool if league.strip().casefold() in str(r.get("league", "")).casefold()]
    # odds-tol 0.05 at 2.00 ≈ 1.2 probability points; keep both checks
    p_tol = max(0.008, min(0.08, tol / 4.0))
    out = []
    for r in pool:
        diffs = {}; pgaps = {}; compared = matched = 0
        wsum = wscore = 0.0
        for k, target in q.items():
            v = r.get(k)
            if v is None:
                continue
            try:
                v = float(v)
            except Exception:
                continue
            compared += 1
            d = abs(v - target)
            g = prob_gap(v, target)
            diffs[k] = round(d, 3)
            if g is not None:
                pgaps[k] = round(g * 100, 2)
            hit = d <= tol or (g is not None and g <= p_tol)
            matched += int(hit)
            w = WEIGHTS.get(k, 0.7)
            wsum += w
            closeness = 1.0 - min(1.0, (g if g is not None else d / max(target, 1)) / max(p_tol * 3, 1e-6))
            wscore += w * max(0.0, closeness)
        if compared < 2:
            continue
        x = dict(r)
        x["_matched_odds"] = matched
        x["_compared_odds"] = compared
        x["_match_ratio"] = round(100 * matched / compared, 1)
        x["_differences"] = diffs
        x["_prob_gaps"] = pgaps
        x["_total_difference"] = round(sum(diffs.values()), 3)
        x["_similarity"] = round(100 * wscore / wsum, 1) if wsum else 0
        out.append(x)
    searched = len(q)
    minimum = max(2, (searched + 1) // 2)
    matches = [x for x in out if x["_matched_odds"] >= minimum]
    matches.sort(key=lambda x: (-x["_similarity"], -x["_matched_odds"], x["_total_difference"]))
    return pool, matches, minimum, False


def expected_goals(q):
    """Poisson λ from 2.5 / 3.5 over odds when present."""
    def lam_from_over(odds, line):
        p = implied(odds)
        if not p:
            return None
        # rough: P(X > line) ≈ p; invert Poisson CDF around line
        # λ ≈ line + 0.5 + logit-ish from over favorite
        return round(line + 0.35 + (p - 0.45) * 2.2, 2)

    lam = None
    if q.get("o25"):
        lam = lam_from_over(q["o25"], 2.5)
    if q.get("o35"):
        l2 = lam_from_over(q["o35"], 3.5)
        lam = round((lam + l2) / 2, 2) if lam and l2 else (l2 or lam)
    return lam


def wilson(k, n, z=1.64):
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    center = (p + z * z / (2 * n)) / d
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return round(100 * max(0, center - half), 1)


def kelly_fraction(p, odds):
    """f* = (p*odds - 1) / (odds - 1). p in 0-1, decimal odds."""
    try:
        p = float(p)
        odds = float(odds)
    except Exception:
        return None
    if p <= 0 or p >= 1 or odds <= 1:
        return None
    f = (p * odds - 1) / (odds - 1)
    if f <= 0:
        return 0.0
    return round(min(f, 0.25), 4)


def signal_engine(stats_obj, prob_groups, n, q=None):
    q = q or {}
    fmap = {}
    omap = {}
    for g in prob_groups:
        for s in g.get("selections", []):
            if isinstance(s.get("fair_percent"), (int, float)):
                fmap[s["name"]] = s["fair_percent"]
            if isinstance(s.get("odds"), (int, float)):
                omap[s["name"]] = s["odds"]
    rows = []
    pairs = [
        ("2,5 Üst", "o25"), ("2,5 Alt", "u25"),
        ("3,5 Üst", "o35"), ("3,5 Alt", "u35"),
        ("KG Var", "btts"), ("KG Yok", "nobtts"),
        ("MS 1", "h"), ("MS X", "d"), ("MS 2", "a"),
        ("6+ Gol", "g6"),
    ]
    hits = int(n or 0)
    for name, key in pairs:
        hv = stats_obj.get(name)
        fv = fmap.get(name)
        if not isinstance(hv, (int, float)):
            continue
        count = round(hits * hv / 100) if hits else 0
        ev = round(hv - fv, 1) if isinstance(fv, (int, float)) else None
        odds = q.get(key) or omap.get(name)
        p = hv / 100.0
        p_safe = (wilson(count, hits) / 100.0) if hits else None
        k_full = kelly_fraction(p, odds) if odds else None
        k_half = round(k_full / 2, 4) if k_full else k_full
        k_cons = kelly_fraction(p_safe, odds) if (odds and p_safe) else None
        rows.append({
            "name": name,
            "odds": odds,
            "historical_percent": hv,
            "fair_percent": fv,
            "edge": ev,
            "wilson_low": wilson(count, hits) if hits else None,
            "kelly": k_full,
            "kelly_half": k_half,
            "kelly_wilson": k_cons,
            "kelly_bankroll_pct": round(k_half * 100, 2) if k_half else 0,
            "signal": "EV+" if ev is not None and ev >= 8 else ("EV-" if ev is not None and ev <= -8 else "nötr"),
        })
    rows.sort(key=lambda x: (x["kelly"] or 0, abs(x["edge"] or 0)), reverse=True)
    return rows


def key_result(k, ft, ht):
    h, a = ft; t = h + a
    return {
        "h": h > a, "d": h == a, "a": h < a,
        "o25": t >= 3, "u25": t <= 2, "o35": t >= 4, "u35": t <= 3,
        "btts": h > 0 and a > 0, "nobtts": h == 0 or a == 0,
        "g6": t >= 6, "g45": t >= 5,
    }.get(k)


def relationship_engine(rows):
    valid = []
    for r in rows:
        ft = score(r.get("ft"))
        if ft:
            valid.append(ft)
    n = len(valid)
    if not n:
        return []
    tests = [
        ("2,5 Üst + KG Var", lambda h, a: h + a >= 3 and h > 0 and a > 0),
        ("2,5 Alt + KG Yok", lambda h, a: h + a <= 2 and (h == 0 or a == 0)),
        ("3,5 Üst + KG Var", lambda h, a: h + a >= 4 and h > 0 and a > 0),
        ("4,5 Üst", lambda h, a: h + a >= 5),
        ("6+ Gol", lambda h, a: h + a >= 6),
        ("MS 1 + 1,5 Üst", lambda h, a: h > a and h + a >= 2),
        ("MS 2 + 1,5 Üst", lambda h, a: h < a and h + a >= 2),
        ("Beraberlik + KG Var", lambda h, a: h == a and h > 0 and a > 0),
    ]
    out = []
    for name, fn in tests:
        c = sum(1 for h, a in valid if fn(h, a))
        out.append({"name": name, "count": c, "sample": n, "percent": round(100 * c / n, 1)})
    return sorted(out, key=lambda x: x["percent"], reverse=True)


def market_comparison(stats_obj, prob_groups):
    hist_map = {
        "h": "MS 1", "d": "MS X", "a": "MS 2",
        "u25": "2,5 Alt", "o25": "2,5 Üst",
        "u35": "3,5 Alt", "o35": "3,5 Üst",
        "btts": "KG Var", "nobtts": "KG Yok",
    }
    out = []
    for g in prob_groups:
        for sel in g.get("selections", []):
            hk = hist_map.get(sel.get("key"))
            hv = stats_obj.get(hk) if hk else None
            fv = sel.get("fair_percent")
            if not isinstance(hv, (int, float)) or not isinstance(fv, (int, float)):
                continue
            out.append({
                "market": g.get("market"), "selection": sel.get("name"),
                "historical_percent": round(hv, 1), "fair_percent": round(fv, 2),
                "difference_points": round(hv - fv, 2),
            })
    return sorted(out, key=lambda x: abs(x["difference_points"]), reverse=True)


def insights(s, prob, matched):
    vals = [(k, v) for k, v in s.items() if k not in {"sample_ft", "sample_ht", "avg_goals", "avg_home_goals", "avg_away_goals", "top_scores"} and isinstance(v, (int, float))]
    vals.sort(key=lambda x: x[1], reverse=True)
    why = []
    if HISTORY_WARNING:
        why.append(HISTORY_WARNING)
    if matched:
        why.append(f"{matched} gerçek geçmiş maç mevcut filtreleri karşıladı.")
    if vals:
        why.append(f"Geçmiş sonuçlarda en yüksek oran {vals[0][0]}: %{vals[0][1]:.1f}.")
    if prob:
        why.append(f"{len(prob)} tam piyasa grubunda bookmaker marjı temizlenebildi.")
    else:
        why.append("Tam karşıt oran grubu olmadığı için marjsız piyasa olasılığı üretilmedi.")
    return why


BANKO_RULES = [
    {"id": "u35", "selection": "3,5 Alt", "target": "u35", "requirements": [("u35", "fair", 80.0)], "backtest": [(40, 34), (35, 30), (36, 29)]},
    {"id": "iyu15", "selection": "İY 1,5 Alt", "target": "iyu15", "requirements": [("iyu15", "fair", 70.0), ("u35", "fair", 50.0), ("nobtts", "fair", 55.0)], "backtest": [(66, 56), (46, 35), (33, 26)]},
    {"id": "h", "selection": "MS 1", "target": "h", "requirements": [("h", "fair", 50.0), ("o25", "fair", 55.0), ("nobtts", "fair", 50.0)], "backtest": [(165, 128), (49, 39), (38, 30)]},
]


def fair_map(prob_groups):
    out = {}
    for g in prob_groups:
        if not g.get("valid"):
            continue
        for x in g.get("selections", []):
            if isinstance(x.get("fair_percent"), (int, float)):
                out[x["key"]] = float(x["fair_percent"])
    return out


def banko_engine(prob_groups):
    fm = fair_map(prob_groups); candidates = []
    for rule in BANKO_RULES:
        checks = []; ok = True
        for key, _, threshold in rule["requirements"]:
            actual = fm.get(key)
            passed = actual is not None and actual >= threshold
            if not passed:
                ok = False
            checks.append({"market": NAMES.get(key, key), "fair_percent": actual, "minimum_percent": threshold, "passed": passed})
        if not ok:
            continue
        total = sum(n for n, w in rule["backtest"]); wins = sum(w for n, w in rule["backtest"])
        folds = [round(100 * w / n, 1) for n, w in rule["backtest"]]
        candidates.append({
            "id": rule["id"], "selection": rule["selection"], "sample": total, "wins": wins,
            "losses": total - wins, "hit_percent": round(100 * wins / total, 1),
            "folds": folds, "minimum_fold_percent": min(folds), "checks": checks,
        })
    candidates.sort(key=lambda x: (x["minimum_fold_percent"], x["sample"]), reverse=True)
    return {
        "status": "BANKO ADAYI" if candidates else "BANKO YOK",
        "candidates": candidates,
        "note": "Banko garanti değildir. Yalnızca sabit kuralları karşılayan ve kronolojik geçmiş testte doğrulanmış adayları gösterir.",
    }


class OddsReq(BaseModel):
    odds: dict[str, float | None]
    tolerance: float = Field(0.05, ge=0, le=5)
    league: str = ""
    limit: int = Field(500, ge=1, le=5000)


@app.get("/")
def root():
    html = ROOT / "index.html"
    if html.exists():
        return FileResponse(html)
    raise HTTPException(404, "index.html yok")


@app.get("/api/meta")
def meta():
    return {
        "history_rows": len(HISTORY),
        "completed_rows": sum(score(x.get("ft")) is not None for x in HISTORY),
        "markets": MARKETS,
        "version": "4.9.4",
        "warning": HISTORY_WARNING,
        "rule": "Yalnızca history.json içindeki gerçek oran ve sonuçlar kullanılır.",
    }


def _odd(v):
    try:
        f = float(str(v).replace(",", "."))
        return f if 1.01 <= f <= 80 else None
    except Exception:
        return None


def _parse_program_rows(raw: str):
    rows = []
    for m in re.finditer(
        r"\[(\d+),'((?:\\'|[^'])*)',\d+,'((?:\\'|[^'])*)','?\d+'?,\d+,'(\d+:\d+)','(\d{2}\.\d{2}\.\d{4})',(.*?)\](?=,\[|\])",
        raw,
    ):
        mac_id, home, away, time, date_s, rest = m.groups()
        parts = []
        buf = ""
        in_q = False
        for ch in rest:
            if ch == "'":
                in_q = not in_q
                continue
            if ch == "," and not in_q:
                parts.append(buf)
                buf = ""
            else:
                buf += ch
        if buf:
            parts.append(buf)
        # parts[0] starts after date field — align with full-row index 8
        def at(i):
            j = i - 8
            return parts[j] if 0 <= j < len(parts) else ""

        league = next((p for p in parts if re.fullmatch(r"[A-ZÇĞİÖŞÜ0-9]{2,8}", p or "")), "")
        h, d, a = _odd(at(16)), _odd(at(17)), _odd(at(18))
        u25, o25 = _odd(at(22)), _odd(at(23))
        code = at(28)
        rows.append({
            "mac_id": mac_id,
            "home": home.replace("\\'", "'"),
            "away": away.replace("\\'", "'"),
            "time": time,
            "date": date_s,
            "league": league,
            "iddaa_code": code if code.isdigit() else None,
            "h": h, "d": d, "a": a, "u25": u25, "o25": o25,
            "morebets": f"https://arsiv.mackolik.com/AjaxHandlers/IddaaHandler.aspx?command=morebets&mac={mac_id}&type=ByLeague",
        })
    return rows


@app.get("/api/bulletin")
def bulletin(date: str = ""):
    """Iddaa program listesi — resmi API değil, tek GET, kırılabilir."""
    url = "https://arsiv.mackolik.com/AjaxHandlers/ProgramDataHandler.ashx?type=6&sortValue=DATE&week=1&day=-1&sort=-1&sortDir=1&groupId=-1&np=0&sport=1"
    try:
        raw = _fetch(url, limit=3000000)
    except Exception as e:
        raise HTTPException(502, "Bülten alınamadı: " + str(e)[:120])
    rows = _parse_program_rows(raw)
    want = ""
    if date.strip():
        # accept 2026-09-22 or 22.09.2026
        ds = date.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", ds):
            y, mo, d = ds.split("-")
            want = f"{d}.{mo}.{y}"
        else:
            want = ds
        rows = [r for r in rows if r["date"] == want]
    return {
        "ok": True,
        "source": "Mackolik ProgramDataHandler",
        "count": len(rows),
        "date": want or "hafta",
        "matches": rows[:400],
        "note": "Resmi API değil. Tek istek. Site şeması değişirse liste boşalır.",
    }


class LinkReq(BaseModel):
    url: str


UA = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
}


def _html_to_text(raw: str):
    raw = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(?:p|div|tr|li|h[1-6])>", "\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = unescape(raw).replace("\xa0", " ")
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n", raw)
    return raw.strip()


def _fetch(url, limit=2500000):
    r = Request(url, headers=UA)
    with urlopen(r, timeout=15) as f:
        data = f.read(limit)
        ctype = f.headers.get_content_charset() or "utf-8"
    try:
        return data.decode(ctype, errors="replace")
    except Exception:
        return data.decode("utf-8", errors="replace")


def _extract_mac_id(url, body=""):
    for src in (url, body):
        m = re.search(r"(?:[?&]mac=|/Mac(?:-Detay)?/)(\d{5,})", src, re.I)
        if m:
            return m.group(1)
        m = re.search(r"macId['\"]?\s*[:=]\s*['\"]?(\d{5,})", src, re.I)
        if m:
            return m.group(1)
    return None


def _morebets_bulletin(raw: str):
    m = re.search(r'Match:"([^"]+)"', raw) or re.search(r'"Match"\s*:\s*"([^"]+)"', raw)
    name = m.group(1) if m else ""
    lines = [name] if name else []
    wanted = {
        "Maç Sonucu": "ms",
        "2,5 Alt/Üst": "25",
        "3,5 Alt/Üst": "35",
        "4,5 Alt/Üst": "45",
        "{{SOV}} Alt/Üst": "sov",
        "Karşılıklı Gol": "kg",
        "1. Yarı 0,5 Alt/Üst": "iy05",
        "1. Yarı 1,5 Alt/Üst": "iy15",
        "İlk Gol": "ilk",
        "İlk Korner": "korner",
        "Toplam Gol Aralığı": "range",
    }
    sov_au = []
    for mm in re.finditer(r'"MarketType":\{"Id":\d+,"Name":"([^"]+)","Title":"[^"]+"\}.*?"Outcomes":\[(.*?)\]', raw):
        title, blob = mm.group(1), mm.group(2)
        outs = re.findall(r'"OutcomeName":"([^"]+)","Odd":([0-9.]+)', blob)
        if not outs or title not in wanted:
            continue
        kind = wanted[title]
        d = {a: b for a, b in outs}
        if kind == "ms" and all(k in d for k in ("1", "X", "2")):
            lines.append(f"Maç Sonucu {d['1']} {d['X']} {d['2']}")
            lines.append(f"1 X 2 {d['1']} {d['X']} {d['2']}")
        elif kind == "25" and "Alt" in d and "Üst" in d:
            lines.append(f"2,5 Alt/Üst {d['Alt']} {d['Üst']}")
        elif kind == "35" and "Alt" in d and "Üst" in d:
            lines.append(f"3,5 Alt/Üst {d['Alt']} {d['Üst']}")
        elif kind == "45" and "Alt" in d and "Üst" in d:
            lines.append(f"4,5 Alt/Üst {d['Alt']} {d['Üst']}")
        elif kind == "sov" and "Alt" in d and "Üst" in d:
            sov_au.append((float(d["Üst"]), d["Alt"], d["Üst"]))
        elif kind == "kg" and "Var" in d:
            yok = d.get("Yok", "")
            lines.append(f"Karşılıklı Gol Var {d['Var']}" + (f" Yok {yok}" if yok else ""))
        elif kind == "iy05" and "Alt" in d and "Üst" in d:
            lines.append(f"1. Yarı 0,5 Alt/Üst {d['Alt']} {d['Üst']}")
        elif kind == "iy15" and "Alt" in d and "Üst" in d:
            lines.append(f"1. Yarı 1,5 Alt/Üst {d['Alt']} {d['Üst']}")
        elif kind == "ilk" and "Olmaz" in d:
            lines.append(f"İlk Gol Olmaz {d['Olmaz']}")
        elif kind == "korner" and "Olmaz" in d:
            lines.append(f"İlk Korner Olmaz {d['Olmaz']}")
        elif kind == "range":
            g = {a.replace(" Gol", "").replace(" ", ""): b for a, b in outs}
            if "4-5" in g:
                lines.append(f"4,5 Alt/Üst proxy g45 {g['4-5']}")
            if "6+" in g:
                lines.append(f"6+ Gol {g['6+']}")
    sov_au.sort()
    if sov_au and not any(x.startswith("4,5 Alt/Üst ") for x in lines):
        _, a, u = sov_au[0]
        lines.append(f"4,5 Alt/Üst {a} {u}")
    return name, "\n".join(lines).strip()


@app.post("/api/match-link")
def match_link(req: LinkReq):
    url = req.url.strip()
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise HTTPException(400, "Geçerli bir maç linki gir.")
    host = u.netloc.lower()
    allowed = ("mackolik.com", "arsiv.mackolik.com", "www.mackolik.com")
    if not any(host == x or host.endswith("." + x) for x in allowed):
        raise HTTPException(400, "Şimdilik Maçkolik maç linkleri destekleniyor.")
    try:
        html = _fetch(url)
        text = _html_to_text(html)
        title = ""
        tm = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
        if tm:
            title = _html_to_text(tm.group(1))
        mac_id = _extract_mac_id(url, html)
        bulletin = ""
        source = "Mackolik"
        if mac_id:
            try:
                raw = _fetch(f"https://arsiv.mackolik.com/AjaxHandlers/IddaaHandler.aspx?command=morebets&mac={mac_id}&type=ByLeague")
                name, bulletin = _morebets_bulletin(raw)
                if name and not title:
                    title = name
                if bulletin:
                    source = "Mackolik Iddaa"
                    text = bulletin + "\n\n" + text
            except Exception:
                pass
        if len(text) < 40:
            raise ValueError("Sayfa içeriği alınamadı")
        return {"ok": True, "url": url, "title": title, "text": text[:120000], "chars": len(text), "source": source, "mac_id": mac_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, "Maç linki sunucudan okunamadı: " + str(e)[:120])


@app.get("/api/selftest")
def selftest():
    return {
        "ok": True,
        "version": "4.9.4",
        "history_rows": len(HISTORY),
        "completed_rows": sum(score(x.get("ft")) is not None for x in HISTORY),
        "endpoints": ["/api/match-link", "/api/odds", "/api/exact-odds", "/api/plus6"],
        "warning": HISTORY_WARNING,
    }


@app.post("/api/odds")
def odds_scan(req: OddsReq):
    q = {}
    for k, v in req.odds.items():
        if k not in MARKETS or v is None:
            continue
        try:
            f = float(v)
        except Exception:
            continue
        if f > 1:
            q[k] = f
    if len(q) < 2:
        raise HTTPException(400, "En az 2 desteklenen gerçek oran bulunmalı.")
    pool, matches, minimum, fallback = match_rows(q, req.tolerance, req.league)
    s = stats(matches)
    prob = probability_engine(q)
    banko = banko_engine(prob)
    relationships = relationship_engine(matches)
    comparison = market_comparison(s, prob)
    sensitivity = []
    for t in sorted(set([max(0.01, round(req.tolerance / 2, 3)), round(req.tolerance, 3), round(req.tolerance * 2, 3)])):
        _, mm, _, _ = match_rows(q, t, req.league)
        sensitivity.append({"tolerance": t, "matched": len(mm)})
    eligible = []
    for r in pool:
        compared = 0
        matched_count = 0
        for k, target in q.items():
            try:
                v = float(r.get(k))
            except Exception:
                continue
            compared += 1
            if abs(v - target) <= req.tolerance:
                matched_count += 1
        if compared >= 2:
            eligible.append((r, matched_count, compared))
    funnel = [
        {"step": "Sonuçlu geçmiş maç", "count": len(pool)},
        {"step": "En az 2 karşılaştırılabilir oran", "count": len(eligible)},
    ]
    for threshold in range(1, minimum + 1):
        funnel.append({
            "step": f"En az {threshold}/{len(q)} oran ±{req.tolerance} eşleşti",
            "count": sum(1 for _, m, _ in eligible if m >= threshold),
        })
    outcome_map = {
        "MS 1": "h", "MS X": "d", "MS 2": "a",
        "2,5 Üst": "o25", "2,5 Alt": "u25",
        "KG Var": "btts", "KG Yok": "nobtts",
        "3,5 Üst": "o35", "3,5 Alt": "u35",
        "6+ Gol": "g6",
    }
    candidates = [(name, s.get(name)) for name in outcome_map if isinstance(s.get(name), (int, float))]
    strongest = max(candidates, key=lambda x: x[1]) if candidates else None
    losses = []
    if strongest:
        kk = outcome_map[strongest[0]]
        for r in matches:
            ft = score(r.get("ft"))
            ht = score(r.get("ht"))
            if ft and key_result(kk, ft, ht) is False:
                item = {k: r.get(k) for k in ["date", "league", "home", "away", "ht", "ft"]}
                item.update({
                    "_matched_odds": r.get("_matched_odds"),
                    "_compared_odds": r.get("_compared_odds"),
                    "_match_ratio": r.get("_match_ratio"),
                    "_differences": r.get("_differences", {}),
                })
                losses.append(item)
    league_counts = {}; date_counts = {}
    for r in matches:
        lg = str(r.get("league") or "Bilinmiyor").strip() or "Bilinmiyor"
        dt = str(r.get("date") or "Bilinmiyor").strip() or "Bilinmiyor"
        league_counts[lg] = league_counts.get(lg, 0) + 1
        ym = dt[:7] if len(dt) >= 7 and dt[4:5] == "-" else dt
        date_counts[ym] = date_counts.get(ym, 0) + 1
    breakdown = {
        "leagues": [{"name": k, "count": v, "percent": round(100 * v / len(matches), 1)} for k, v in sorted(league_counts.items(), key=lambda x: (-x[1], x[0]))[:12]] if matches else [],
        "periods": [{"name": k, "count": v, "percent": round(100 * v / len(matches), 1)} for k, v in sorted(date_counts.items(), key=lambda x: x[0], reverse=True)[:12]] if matches else [],
        "sample": len(matches),
    }
    sample_audit = {
        "matched_sample": len(matches),
        "completed_pool": len(pool),
        "coverage_percent": round(100 * len(matches) / len(pool), 2) if pool else 0,
        "warning": "Örneklem 30 maçın altında; yüzdeleri tek başına güçlü kanıt olarak yorumlama." if len(matches) < 30 else None,
        "source": "history.json içindeki sonuçlu gerçek geçmiş maçlar",
    }
    return {
        "method": f"{len(q)} gerçek oran tarandı. En az {minimum}/{len(q)} oran ±{req.tolerance} içinde eşleşti.",
        "sample_audit": sample_audit,
        "searched_odds": q,
        "searched_count": len(q),
        "tolerance": req.tolerance,
        "pool_size": len(pool),
        "matched": len(matches),
        "returned": min(len(matches), req.limit),
        "minimum_match_count": minimum,
        "best_match_count": matches[0]["_matched_odds"] if matches else 0,
        "stats": s,
        "probability_engine": prob,
        "banko": banko,
        "market_comparison": comparison,
        "relationships": relationships,
        "breakdown": breakdown,
        "sensitivity": sensitivity,
        "funnel": funnel,
        "strongest_history": {"market": strongest[0], "percent": strongest[1]} if strongest else None,
        "counterexamples": losses[:12],
        "why": insights(s, prob, len(matches)),
        "expected_goals": expected_goals(q),
        "signals": signal_engine(s, prob, s.get("sample_ft") or 0, q),
        "matches": matches[: req.limit],
    }


EXACT_CATEGORIES = {
    "MS": ["h", "d", "a"],
    "ALT / ÜST": ["u25", "o25", "u35", "o35", "g6", "g45"],
    "KG": ["btts", "nobtts"],
    "İY": ["iyu15", "iyo15"],
    "KORNER": [],
}


def exact_equal(a, b):
    try:
        return float(a) == float(b)
    except Exception:
        return False


def exact_rows(q, keys):
    active = [k for k in keys if k in q]
    if not active:
        return [], active
    rows = []
    for r in HISTORY:
        if score(r.get("ft")) is None:
            continue
        if all(r.get(k) is not None and exact_equal(r.get(k), q[k]) for k in active):
            rows.append(r)
    return rows, active


def exact_summary(rows, category=None):
    s = stats(rows)
    n = s.get("sample_ft", 0)
    bycat = {
        "MS": ["MS 1", "MS X", "MS 2"],
        "ALT / ÜST": ["1,5 Üst", "1,5 Alt", "2,5 Üst", "2,5 Alt", "3,5 Üst", "3,5 Alt", "4,5 Üst", "6+ Gol"],
        "KG": ["KG Var", "KG Yok"],
        "İY": ["İY 1", "İY X", "İY 2"],
    }
    labels = bycat.get(category, ["MS 1", "MS X", "MS 2", "2,5 Üst", "2,5 Alt", "KG Var", "KG Yok"])
    outcomes = []
    for name in labels:
        v = s.get(name)
        if isinstance(v, (int, float)):
            outcomes.append({"name": name, "percent": v, "count": round(n * v / 100) if n else 0})
    outcomes.sort(key=lambda x: (-x["percent"], -x["count"], x["name"]))
    return {"sample": n, "outcomes": outcomes, "top": outcomes[:6]}


@app.post("/api/exact-odds")
def exact_odds_scan(req: OddsReq):
    q = {}
    for k, v in req.odds.items():
        if k not in MARKETS or v is None:
            continue
        try:
            f = float(v)
        except Exception:
            continue
        if f > 1:
            q[k] = f
    if not q:
        raise HTTPException(400, "Desteklenen en az 1 gerçek oran bulunmalı.")
    categories = []
    for name, keys in EXACT_CATEGORIES.items():
        if name == "KORNER":
            categories.append({"category": name, "status": "VERİ YOK", "used_odds": {}, "matched": 0, "summary": {"sample": 0, "outcomes": [], "top": []}, "matches": [], "note": "history.json içinde korner oran sütunu bulunmuyor."})
            continue
        rows, active = exact_rows(q, keys)
        if not active:
            categories.append({"category": name, "status": "ORAN GİRİLMEDİ", "used_odds": {}, "matched": 0, "summary": {"sample": 0, "outcomes": [], "top": []}, "matches": []})
            continue
        categories.append({
            "category": name,
            "status": "EŞLEŞME VAR" if rows else "BİREBİR EŞLEŞME YOK",
            "used_odds": {k: q[k] for k in active},
            "matched": len(rows),
            "summary": exact_summary(rows, name),
            "matches": [{k: r.get(k) for k in ["date", "league", "home", "away", "ht", "ft"]} for r in rows[:200]],
        })
    allkeys = list(q)
    combined, _ = exact_rows(q, allkeys)
    return {
        "method": "TOLERANS YOK — yalnızca girilen oranlarla sayısal olarak birebir aynı geçmiş kayıtlar kullanılır.",
        "searched_odds": q,
        "categories": categories,
        "combined": {
            "matched": len(combined),
            "used_odds": q,
            "summary": exact_summary(combined),
            "matches": [{k: r.get(k) for k in ["date", "league", "home", "away", "ht", "ft"]} for r in combined[:300]],
        },
        "corner_available": False,
        "source_rows": len(HISTORY),
        "completed_rows": sum(score(x.get("ft")) is not None for x in HISTORY),
    }


class Plus6Req(BaseModel):
    o25: float | None = None
    o35: float | None = None
    o45: float | None = None
    g45: float | None = None
    btts: float | None = None
    iy05: float | None = None
    nofirst: float | None = None
    g6: float | None = None
    iyu15: float | None = None
    iyo15: float | None = None


class KellyReq(BaseModel):
    odds: float
    probability_percent: float
    bankroll: float | None = None


@app.post("/api/kelly")
def kelly_api(req: KellyReq):
    p = req.probability_percent / 100.0
    f = kelly_fraction(p, req.odds)
    half = round(f / 2, 4) if f else f
    stake = round(half * req.bankroll, 2) if (half and req.bankroll) else None
    ev = round(p * req.odds - 1, 4) if req.odds > 1 else None
    return {
        "odds": req.odds,
        "p": round(p, 4),
        "formula": "f* = (p·odds − 1) / (odds − 1)",
        "kelly": f,
        "kelly_half": half,
        "kelly_pct": round((f or 0) * 100, 2),
        "kelly_half_pct": round((half or 0) * 100, 2),
        "expected_value": ev,
        "stake": stake,
        "note": "Yarım Kelly önerilir. f*=0 ise değer yok; bankrollun %25 tavanı uygulanır.",
    }


@app.post("/api/plus6")
def plus6(q: Plus6Req):
    o45 = q.o45 if q.o45 is not None else q.g45
    rules = [
        ("2,5 Üst", q.o25, 1.20, 1.28),
        ("3,5 Üst", q.o35, 1.66, 1.89),
        ("4,5 Üst / g45", o45, 2.64, 3.14),
        ("KG Var", q.btts, 1.22, 1.87),
    ]
    output = []
    hit = 0
    for name, v, lo, hi in rules:
        m = v is not None and lo <= v <= hi
        hit += bool(m)
        output.append({"name": name, "value": v, "range": [lo, hi], "match": bool(m)})
    last = (q.iy05 is not None and 1.05 <= q.iy05 <= 1.08) or (q.nofirst is not None and 22.10 <= q.nofirst <= 26.00)
    if not last and q.g6 is not None and q.g6 <= 9.5:
        last = True
    hit += bool(last)
    output.append({
        "name": "İY 0,5 / İlk Gol Olmaz / 6+ Gol proxy",
        "values": [q.iy05, q.nofirst, q.g6],
        "ranges": [[1.05, 1.08], [22.10, 26.00], [None, 9.5]],
        "match": bool(last),
    })
    note = "Yalnızca kayıtlı +6 referans bantlarıyla karşılaştırmadır. o45 yoksa g45 kullanılır."
    if HISTORY_WARNING:
        note = HISTORY_WARNING + " " + note
    return {
        "matched_rules": hit,
        "total_rules": 5,
        "compatibility_percent": round(hit / 5 * 100),
        "rules": output,
        "note": note,
    }
