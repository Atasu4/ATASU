from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from html import unescape
from pathlib import Path
from collections import Counter
import json, re, os, time

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
app = FastAPI(title="ATASU Intelligence", version="5.1.1")
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
            z["sh1" if sh >= 1 else "sh0"] += 1
            z["sh2" if sh >= 2 else "shlt2"] += 1
            z["both_halves" if fh >= 1 and sh >= 1 else "not_both_halves"] += 1

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
        "2.Y 1+ Gol": p("sh1", nh), "2.Y 2+ Gol": p("sh2", nh),
        "Her iki yarı gol": p("both_halves", nh),
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


def _fact(n):
    x = 1
    for i in range(2, n + 1):
        x *= i
    return x


def poisson_pmf(k, lam):
    if lam is None or lam <= 0:
        return None
    return (lam ** k) * (2.718281828 ** (-lam)) / _fact(k)


def poisson_board(lam, home_share=0.55):
    if not lam:
        return None
    lh = max(0.15, lam * home_share)
    la = max(0.15, lam - lh)
    scores = []
    p_o25 = p_btts = p_g6 = 0.0
    for h in range(0, 8):
        ph = poisson_pmf(h, lh)
        for a in range(0, 8):
            pa = poisson_pmf(a, la)
            p = ph * pa
            t = h + a
            if t >= 3:
                p_o25 += p
            if h and a:
                p_btts += p
            if t >= 6:
                p_g6 += p
            scores.append({"score": f"{h}-{a}", "percent": round(p * 100, 2)})
    scores.sort(key=lambda x: -x["percent"])
    return {
        "lambda_total": lam,
        "lambda_home": round(lh, 2),
        "lambda_away": round(la, 2),
        "p_o25": round(p_o25 * 100, 1),
        "p_btts": round(p_btts * 100, 1),
        "p_g6": round(p_g6 * 100, 1),
        "top": scores[:8],
        "note": "Bağımsız Poisson; Dixon-Coles düzeltmesi yok. Ev payı 0.55 varsayımı.",
    }


def late_goal_profile(rows):
    n = sh1 = sh2 = both = 0
    for r in rows:
        ft = score(r.get("ft"))
        ht = score(r.get("ht"))
        if not ft or not ht:
            continue
        n += 1
        sh = (ft[0] + ft[1]) - (ht[0] + ht[1])
        if sh >= 1:
            sh1 += 1
        if sh >= 2:
            sh2 += 1
        if (ht[0] + ht[1]) >= 1 and sh >= 1:
            both += 1
    if not n:
        return {"sample": 0}
    return {
        "sample": n,
        "second_half_1plus_percent": round(100 * sh1 / n, 1),
        "second_half_2plus_percent": round(100 * sh2 / n, 1),
        "both_halves_percent": round(100 * both / n, 1),
        "wilson_sh1": wilson(sh1, n),
        "note": "Geç gol dakikası history.json'da yok; 2. yarı golü proxy olarak kullanılır.",
    }


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
        ("2.Y 1+ Gol", None),
        ("2.Y 2+ Gol", None),
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


# history.json sonuçlu maçlardan türetilmiş oran bantları (n>=220, isabet >=73%)
EMPIRICAL_RULES = [
    {
        "id": "u35_u25",
        "selection": "3,5 Alt",
        "need": [("u35", 1.01, 1.30), ("u25", 1.01, 1.45)],
        "sample": 353, "wins": 287, "hit_percent": 81.3,
        "why": "3,5 Alt ≤1.30 ve 2,5 Alt ≤1.45 olan 353 maçta 287 kez 3,5 alt geldi.",
    },
    {
        "id": "u35_nobtts",
        "selection": "3,5 Alt",
        "need": [("u35", 1.01, 1.28), ("nobtts", 1.01, 1.55)],
        "sample": 379, "wins": 307, "hit_percent": 81.0,
        "why": "3,5 Alt ≤1.28 ve KG Yok ≤1.55 olan 379 maçta 307 kez 3,5 alt geldi.",
    },
    {
        "id": "ms2_short",
        "selection": "MS 2",
        "need": [("a", 1.01, 1.25)],
        "sample": 220, "wins": 176, "hit_percent": 80.0,
        "why": "MS 2 oranı ≤1.25 olan 220 maçta 176 deplasman kazandı.",
    },
    {
        "id": "iyu15_u25",
        "selection": "İY 1,5 Alt",
        "need": [("iyu15", 1.01, 1.28), ("u25", 1.01, 1.45)],
        "sample": 285, "wins": 224, "hit_percent": 78.6,
        "why": "İY 1,5 Alt ≤1.28 ve 2,5 Alt ≤1.45 olan 285 maçta 224 kez İY 0-0 veya 1 gol.",
    },
    {
        "id": "u35_tight",
        "selection": "3,5 Alt",
        "need": [("u35", 1.01, 1.25)],
        "sample": 2880, "wins": 2157, "hit_percent": 74.9,
        "why": "3,5 Alt ≤1.25 olan 2880 maçta 2157 kez 3 gol veya daha az.",
    },
    {
        "id": "iyu15_tight",
        "selection": "İY 1,5 Alt",
        "need": [("iyu15", 1.01, 1.25)],
        "sample": 723, "wins": 540, "hit_percent": 74.7,
        "why": "İY 1,5 Alt ≤1.25 olan 723 maçta 540 kez ilk yarı 0-1 gol.",
    },
    {
        "id": "ms1_short",
        "selection": "MS 1",
        "need": [("h", 1.01, 1.25)],
        "sample": 671, "wins": 499, "hit_percent": 74.4,
        "why": "MS 1 ≤1.25 olan 671 maçta 499 ev kazandı.",
    },
    {
        "id": "ms1_nobtts",
        "selection": "MS 1",
        "need": [("h", 1.01, 1.45), ("nobtts", 1.01, 1.50)],
        "sample": 261, "wins": 192, "hit_percent": 73.6,
        "why": "MS 1 ≤1.45 ve KG Yok ≤1.50 olan 261 maçta 192 ev kazandı.",
    },
]
LH_URL = "https://eagle-sapphire-quiet-bold.grok.me/"

BETWATCH_API = os.environ.get("BETWATCH_API", "https://api.betwatch.fr/api/v1")
BETWATCH_TOKEN = os.environ.get("BETWATCH_API_KEY", "").strip() or "3998ca22082238518d38af6f4aff0eca45e75e9b"
_BW_CACHE = {"prematch": None, "live": None, "ts": 0.0}
_BW_TTL = 40

BW_MARKET_MAP = {
    "Match Odds": {"home": "h", "the draw": "d", "draw": "d", "away": "a"},
    "Over/Under 2.5 Goals": {"under 2.5 goals": "u25", "over 2.5 goals": "o25"},
    "Over/Under 3.5 Goals": {"under 3.5 goals": "u35", "over 3.5 goals": "o35"},
    "Both teams to Score?": {"yes": "btts", "no": "nobtts"},
    "First Half Goals 1.5": {"under 1.5 goals": "iyu15", "over 1.5 goals": "iyo15"},
    "Over/Under 5.5 Goals": {"over 5.5 goals": "g6"},
}


def _bw_fetch(path):
    if not BETWATCH_TOKEN:
        return None, "BETWATCH_API_KEY yok"
    url = BETWATCH_API.rstrip("/") + path
    try:
        req = Request(url, headers={"Authorization": "Token " + BETWATCH_TOKEN, "Accept": "application/json"})
        with urlopen(req, timeout=18) as f:
            return json.loads(f.read().decode("utf-8", errors="replace")), None
    except Exception as e:
        return None, str(e)[:160]


def _bw_bundle(force=False):
    now = time.time()
    if not force and _BW_CACHE["prematch"] is not None and now - _BW_CACHE["ts"] < _BW_TTL:
        return _BW_CACHE
    pre, e1 = _bw_fetch("/football/prematch")
    live, e2 = _bw_fetch("/football/live")
    _BW_CACHE["prematch"] = pre if isinstance(pre, list) else []
    _BW_CACHE["live"] = live if isinstance(live, list) else []
    _BW_CACHE["ts"] = now
    _BW_CACHE["error"] = ", ".join(x for x in (e1, e2) if x)
    return _BW_CACHE


def _norm_team(s):
    s = (s or "").casefold()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = s.replace("ü", "u").replace("ö", "o").replace("ş", "s").replace("ç", "c").replace("ı", "i").replace("ğ", "g")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    drop = {"fc", "cf", "sk", "fk", "afc", "sc", "the", "de", "united", "city", "w"}
    parts = [p for p in s.split() if p and p not in drop]
    return " ".join(parts)


def _team_hit(a, b):
    a, b = _norm_team(a), _norm_team(b)
    if not a or not b:
        return 0
    if a == b or a in b or b in a:
        return 3
    sa, sb = set(a.split()), set(b.split())
    if sa and sb and (sa <= sb or sb <= sa):
        return 2
    if sa & sb:
        return 1
    return 0


def _parse_home_away(title=""):
    h, a = _parse_teams(title)
    return h, a


def _flatten_bw_match(m, source="prematch"):
    teams = m.get("teams") or {}
    home, away = teams.get("v1") or "", teams.get("v2") or ""
    markets = {}
    for mk in m.get("markets") or []:
        name = mk.get("name") or ""
        mapping = BW_MARKET_MAP.get(name)
        if not mapping:
            continue
        total_vol = 0.0
        rows = []
        for rn in mk.get("runners") or []:
            rn_name = str(rn.get("name") or "")
            key = None
            low = rn_name.casefold()
            if name == "Match Odds":
                if low == home.casefold():
                    key = "h"
                elif low == away.casefold():
                    key = "a"
                elif "draw" in low:
                    key = "d"
            else:
                key = mapping.get(low)
            odd = rn.get("odd")
            vol = rn.get("volume")
            try:
                odd = float(odd) if odd is not None else None
            except Exception:
                odd = None
            try:
                vol = float(vol) if vol is not None else 0.0
            except Exception:
                vol = 0.0
            total_vol += vol
            rows.append({"key": key, "name": rn_name, "odd": odd, "volume": round(vol, 2)})
        for row in rows:
            share = round(100 * row["volume"] / total_vol, 1) if total_vol else None
            row["money_pct"] = share
            if row["key"]:
                markets[row["key"]] = {
                    "odd": row["odd"],
                    "volume": row["volume"],
                    "money_pct": share,
                    "market": name,
                    "runner": row["name"],
                }
        markets["_vol_" + name] = round(total_vol, 2)
    return {
        "match_id": m.get("match_id"),
        "home": home,
        "away": away,
        "league": m.get("league"),
        "country": m.get("country"),
        "kickoff": m.get("kickoff"),
        "source": source,
        "markets": {k: v for k, v in markets.items() if not str(k).startswith("_vol_")},
        "volumes": {k[5:]: v for k, v in markets.items() if str(k).startswith("_vol_")},
    }


def betwatch_find(title="", home="", away="", q=None):
    if not home and not away:
        home, away = _parse_home_away(title)
    bundle = _bw_bundle()
    pool = []
    for src in ("live", "prematch"):
        for m in bundle.get(src) or []:
            pool.append(_flatten_bw_match(m, src))
    if not pool:
        return {"ok": False, "error": bundle.get("error") or "Betwatch boş", "matched": None, "candidates": []}
    scored = []
    for m in pool:
        sc = _team_hit(home, m["home"]) + _team_hit(away, m["away"])
        if sc <= 0 and home:
            sc = _team_hit(home, m["home"]) + _team_hit(home, m["away"])
        if sc <= 0:
            continue
        scored.append((sc, m))
    scored.sort(key=lambda x: -x[0])
    best = scored[0][1] if scored and scored[0][0] >= 2 else None
    overlay = []
    if best and q:
        for k, hist_odd in q.items():
            bw = (best.get("markets") or {}).get(k)
            if not bw:
                continue
            implied_p = implied(bw.get("odd") or hist_odd)
            overlay.append({
                "key": k,
                "name": NAMES.get(k, k),
                "book_odd": hist_odd,
                "betwatch_odd": bw.get("odd"),
                "volume": bw.get("volume"),
                "money_pct": bw.get("money_pct"),
                "implied_percent": round(100 * implied_p, 1) if implied_p else None,
            })
    return {
        "ok": True,
        "error": bundle.get("error") or None,
        "token_set": bool(BETWATCH_TOKEN),
        "matched": best,
        "overlay": overlay,
        "candidates": [{"score": s, "home": m["home"], "away": m["away"], "league": m["league"], "kickoff": m["kickoff"]} for s, m in scored[:6]],
        "note": "Betfair Exchange eşleşen para. Düşük volume gürültüdür. Kalıp + money aynı tarafta ve oran ölmemişse AL.",
    }


def money_signals(stats_obj, overlay, q=None):
    q = q or {}
    out = []
    name_to_key = {
        "MS 1": "h", "MS X": "d", "MS 2": "a",
        "2,5 Üst": "o25", "2,5 Alt": "u25",
        "3,5 Üst": "o35", "3,5 Alt": "u35",
        "KG Var": "btts", "KG Yok": "nobtts",
        "İY 1,5 Alt": "iyu15", "İY 1,5 Üst": "iyo15",
    }
    ov = {x["key"]: x for x in overlay or []}
    for name, key in name_to_key.items():
        hv = stats_obj.get(name) if stats_obj else None
        row = ov.get(key)
        if not row and not isinstance(hv, (int, float)):
            continue
        implied_p = row.get("implied_percent") if row else (round(100 * implied(q.get(key)), 1) if implied(q.get(key)) else None)
        money = row.get("money_pct") if row else None
        vol = row.get("volume") if row else None
        edge = round(hv - implied_p, 1) if isinstance(hv, (int, float)) and isinstance(implied_p, (int, float)) else None
        signal = "PAS"
        if edge is not None and money is not None and (vol or 0) >= 400:
            if edge >= 6 and money >= 45:
                signal = "AL"
            elif edge <= -6 and money >= 55:
                signal = "PAHALI"
            elif edge >= 8 and money < 35:
                signal = "TERS/MONEY YOK"
        elif edge is not None:
            signal = "EV+" if edge >= 8 else ("EV-" if edge <= -8 else "nötr")
        out.append({
            "name": name,
            "key": key,
            "historical_percent": hv,
            "implied_percent": implied_p,
            "money_pct": money,
            "volume": vol,
            "betwatch_odd": row.get("betwatch_odd") if row else None,
            "edge": edge,
            "signal": signal,
        })
    out.sort(key=lambda x: ({"AL": 3, "EV+": 2, "TERS/MONEY YOK": 1, "nötr": 0, "PAS": -1, "EV-": -2, "PAHALI": -3}.get(x["signal"], 0), abs(x["edge"] or 0)), reverse=True)
    return out


def empirical_banko(q):
    hit = []
    miss = []
    for rule in EMPIRICAL_RULES:
        checks = []
        ok = True
        for key, lo, hi in rule["need"]:
            v = q.get(key)
            try:
                v = float(v) if v is not None else None
            except Exception:
                v = None
            passed = v is not None and lo <= v <= hi
            if not passed:
                ok = False
            checks.append({"key": key, "odds": v, "range": [lo, hi], "passed": passed})
        row = {
            "id": rule["id"],
            "selection": rule["selection"],
            "hit_percent": rule["hit_percent"],
            "sample": rule["sample"],
            "wins": rule["wins"],
            "why": rule["why"],
            "checks": checks,
            "match": ok,
        }
        (hit if ok else miss).append(row)
    hit.sort(key=lambda x: (-x["hit_percent"], -x["sample"]))
    status = "BANKO ADAYI" if hit else "BANKO YOK"
    if hit and hit[0]["hit_percent"] >= 78:
        status = "BANKO GÜÇLÜ"
    return {
        "status": status,
        "matched": hit,
        "unmatched": miss,
        "source": "history.json sonuçlu maçlar, 2026-05 … 2026-09",
        "lh_url": LH_URL,
        "note": "Kural geçmiş sıklıktır; gelecek maçı garanti etmez. n küçük olan kural daha kırılgan.",
    }


class OddsReq(BaseModel):
    odds: dict[str, float | None]
    tolerance: float = Field(0.05, ge=0, le=5)
    league: str = ""
    limit: int = Field(500, ge=1, le=5000)
    title: str = ""
    page_text: str = ""


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
        "version": "5.1.2",
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
        home, away = _parse_teams(title)
        bw = betwatch_find(title, home or "", away or "")
        return {
            "ok": True, "url": url, "title": title, "home": home, "away": away,
            "text": text[:120000], "chars": len(text), "source": source, "mac_id": mac_id,
            "betwatch": bw,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, "Maç linki sunucudan okunamadı: " + str(e)[:120])


@app.get("/api/selftest")
def selftest():
    return {
        "ok": True,
        "version": "5.1.2",
        "history_rows": len(HISTORY),
        "completed_rows": sum(score(x.get("ft")) is not None for x in HISTORY),
        "endpoints": ["/api/match-link", "/api/odds", "/api/exact-odds", "/api/plus6", "/api/betwatch"],
        "betwatch_token": bool(BETWATCH_TOKEN),
        "warning": HISTORY_WARNING,
    }


class BetwatchReq(BaseModel):
    title: str = ""
    home: str = ""
    away: str = ""
    odds: dict[str, float | None] | None = None


@app.post("/api/betwatch")
def betwatch_api(req: BetwatchReq):
    q = {}
    for k, v in (req.odds or {}).items():
        try:
            f = float(v)
        except Exception:
            continue
        if k in MARKETS and f > 1:
            q[k] = f
    return betwatch_find(req.title, req.home, req.away, q or None)


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
    ebanko = empirical_banko(q)
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
    bw = betwatch_find(req.title or "", q=q)
    bw["signals"] = money_signals(s, bw.get("overlay"), q)
    p6 = plus6_payload(q)
    yorum = compact_yorum(s, matches, title=req.title or "", league=req.league or "", q=q, bw=bw, p6=p6)
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
        "empirical_banko": ebanko,
        "market_comparison": comparison,
        "relationships": relationships,
        "breakdown": breakdown,
        "sensitivity": sensitivity,
        "funnel": funnel,
        "strongest_history": {"market": strongest[0], "percent": strongest[1]} if strongest else None,
        "counterexamples": losses[:12],
        "why": insights(s, prob, len(matches)),
        "expected_goals": expected_goals(q),
        "poisson": poisson_board(
            expected_goals(q),
            home_share=(s["avg_home_goals"] / s["avg_goals"]) if (s.get("avg_goals") and s.get("avg_home_goals")) else 0.55,
        ),
        "late_goal": late_goal_profile(matches),
        "signals": signal_engine(s, prob, s.get("sample_ft") or 0, q),
        "betwatch": bw,
        "yorum": yorum,
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


def _parse_teams(title: str):
    t = re.sub(r"\s+", " ", (title or "")).strip()
    t = re.split(r"\s*\|\s*|\s+-\s+Mackolik|\s+Canli|\s+Canlı", t, maxsplit=1)[0]
    for sep in (" vs ", " VS ", " v ", " — ", " – ", " - "):
        if sep in t:
            a, b = t.split(sep, 1)
            a, b = a.strip(" .:-"), b.strip(" .:-")
            if a and b and len(a) < 48 and len(b) < 48:
                return a, b
    return None, None


def _team_form(name, n=5):
    if not name:
        return None
    key = name.casefold()
    rows = []
    for r in HISTORY:
        ft = score(r.get("ft"))
        if not ft:
            continue
        home = str(r.get("home") or "")
        away = str(r.get("away") or "")
        if key not in home.casefold() and key not in away.casefold():
            continue
        rows.append((str(r.get("date") or ""), home, away, ft))
    rows.sort(key=lambda x: x[0], reverse=True)
    rows = rows[:n]
    if not rows:
        return None
    w = d = l = 0
    gf = ga = 0
    letters = []
    for _, home, away, ft in rows:
        ev = key in home.casefold()
        g_for, g_ag = (ft[0], ft[1]) if ev else (ft[1], ft[0])
        gf += g_for
        ga += g_ag
        if g_for > g_ag:
            w += 1
            letters.append("W")
        elif g_for == g_ag:
            d += 1
            letters.append("D")
        else:
            l += 1
            letters.append("L")
    k = len(rows)
    return {
        "ad": name,
        "n": k,
        "WDL": f"{w}-{d}-{l}",
        "ort": f"{round(gf/k, 1)}/{round(ga/k, 1)}",
        "form": "".join(letters),
    }


def compact_yorum(s, matches, title="", league="", q=None, bw=None, p6=None):
    q = q or {}
    n = s.get("sample_ft") or 0
    ev, dep = _parse_teams(title)
    ligler = Counter(str(r.get("league") or "?") for r in matches)
    lig_txt = " ".join(f"{k}×{v}" for k, v in ligler.most_common(4))
    lines = []
    head = (title.split("|")[0].strip() if title else "özet")
    if league:
        head += " · " + league
    lines.append(head[:90])
    if not n:
        lines.append("havuz boş · birebir/benzer sonuç yok")
        if bw and not bw.get("matched"):
            lines.append("betfair eşleşme yok")
        return "\n".join(lines)
    lines.append(f"n={n}" + (f" · {lig_txt}" if lig_txt else "") + " · farklı lig=kalıp")

    def g(name):
        v = s.get(name)
        return None if not isinstance(v, (int, float)) else v

    ms = f"ms 1 %{g('MS 1') or 0:.0f} · X %{g('MS X') or 0:.0f} · 2 %{g('MS 2') or 0:.0f}"
    iy = f"iy 1 %{g('İY 1') or 0:.0f} · X %{g('İY X') or 0:.0f} · 2 %{g('İY 2') or 0:.0f}"
    lines.append(ms + " · " + iy)
    tops = s.get("top_scores") or []
    if tops:
        lines.append("ms sık " + " ".join(f"{t['score']} %{t['percent']:.0f}" for t in tops[:3]))
    lines.append(
        f"2.5ü %{g('2,5 Üst') or 0:.0f} · 3.5ü %{g('3,5 Üst') or 0:.0f} · kg %{g('KG Var') or 0:.0f} · "
        f"iy gol — · 2.y %{g('2.Y 1+ Gol') or 0:.0f}"
    )
    if s.get("avg_goals") is not None:
        lines.append(f"ort gol {s['avg_goals']} ev {s.get('avg_home_goals')} / dep {s.get('avg_away_goals')}")
    fe = _team_form(ev) if ev else None
    fd = _team_form(dep) if dep else None
    if fe or fd:
        bit = []
        if fe:
            bit.append(f"ev {fe['ad']} {fe['WDL']} {fe['ort']} {fe['form']}")
        if fd:
            bit.append(f"dep {fd['ad']} {fd['WDL']} {fd['ort']} {fd['form']}")
        lines.append(" · ".join(bit))
    o25 = g("2,5 Üst") or 0
    u25 = g("2,5 Alt") or 0
    p1 = g("MS 1") or 0
    px = g("MS X") or 0
    p2 = g("MS 2") or 0
    kg = g("KG Var") or 0
    okuma = []
    if o25 >= 65:
        okuma.append("havuz golcü")
    elif o25 <= 40:
        okuma.append("havuz düşük skor")
    else:
        okuma.append("orta gol")
    lider, lp = max([("1", p1), ("X", px), ("2", p2)], key=lambda x: x[1])
    if lp >= 45:
        okuma.append("analog " + ("ev" if lider == "1" else "dep" if lider == "2" else "X"))
    else:
        okuma.append("ms dağınık")
    if kg >= 60:
        okuma.append("kg sık")
    elif kg and kg <= 35:
        okuma.append("tek kapı var")
    if p6 and isinstance(p6.get("compatibility_percent"), (int, float)):
        okuma.append(f"+6 %{p6['compatibility_percent']}")
    lines.append("okuma: " + " · ".join(okuma))

    sigs = (bw or {}).get("signals") or money_signals(s, (bw or {}).get("overlay"), q)
    matched_bw = (bw or {}).get("matched")
    if not BETWATCH_TOKEN:
        lines.append("betfair: anahtar yok")
    elif not matched_bw:
        lines.append("betfair: bu maç exchange'de yok veya isim eşleşmedi")
    else:
        mh, ma = matched_bw.get("home"), matched_bw.get("away")
        lines.append(f"betfair: {mh} - {ma} · {matched_bw.get('source') or 'prematch'}")
        money_bits = []
        for key, label in [("h", "1"), ("d", "X"), ("a", "2"), ("o25", "2.5ü"), ("u25", "2.5a"), ("btts", "kg"), ("nobtts", "kgy")]:
            mk = (matched_bw.get("markets") or {}).get(key) or {}
            if mk.get("money_pct") is None and mk.get("odd") is None:
                continue
            bit = label
            if mk.get("odd"):
                bit += f" {mk['odd']}"
            if mk.get("money_pct") is not None:
                bit += f" %{mk['money_pct']:.0f}"
            if mk.get("volume"):
                bit += f" €{int(mk['volume'])}"
            money_bits.append(bit)
        if money_bits:
            lines.append("para " + " · ".join(money_bits[:7]))
        al = [x["name"] for x in sigs if x.get("signal") == "AL"]
        pahali = [x["name"] for x in sigs if x.get("signal") in ("PAHALI", "EV-")]
        ters = [x["name"] for x in sigs if x.get("signal") == "TERS/MONEY YOK"]
        evp = [x["name"] for x in sigs if x.get("signal") == "EV+"]
        karar = []
        if al:
            karar.append("AL " + ", ".join(al[:3]))
        elif evp:
            karar.append("kalıp+ " + ", ".join(evp[:3]))
        if pahali:
            karar.append("pahalı " + ", ".join(pahali[:3]))
        if ters:
            karar.append("para ters " + ", ".join(ters[:2]))
        if not karar:
            # fuse hist vs money even without volume threshold
            top_money = None
            best_pct = -1
            for key, label in [("h", "MS 1"), ("d", "MS X"), ("a", "MS 2"), ("o25", "2,5 Üst"), ("u25", "2,5 Alt"), ("btts", "KG Var")]:
                mk = (matched_bw.get("markets") or {}).get(key) or {}
                pct = mk.get("money_pct") or 0
                if pct > best_pct:
                    best_pct = pct
                    top_money = label
            hist_side = {"1": "MS 1", "X": "MS X", "2": "MS 2"}.get(lider)
            if o25 >= 60 and top_money in ("2,5 Üst", "KG Var"):
                karar.append("kalıp ve para gol tarafında · oran kısaysa chase etme")
            elif o25 <= 45 and top_money == "2,5 Alt":
                karar.append("kalıp ve para alt tarafta")
            elif hist_side and top_money == hist_side:
                karar.append(f"kalıp+para {hist_side}")
            elif hist_side and top_money and top_money != hist_side:
                karar.append(f"kalıp {hist_side} · para {top_money} · çelişki")
            else:
                karar.append("betfair teyit zayıf")
        lines.append("birleşik: " + " · ".join(karar))

    lines.append("birebir 0 olabilir · tablo kanıt değil kalıp+para")
    return "\n".join(lines)


def brief_from_odds(q, tol=0.05, league="", limit=200, title=""):
    match_title = title or ""
    pool, matches, minimum, _ = match_rows(q, tol, league)
    s = stats(matches)
    n = s.get("sample_ft") or 0
    p6 = plus6_payload(q)
    lines = []
    title = f"{n} eşleşen sonuçlu maç (±{tol}" + (f", {league}" if league.strip() else "") + ")."
    if n:
        parts = []
        for label, key in [
            ("2,5 Üst", "2,5 Üst"), ("2,5 Alt", "2,5 Alt"),
            ("KG Var", "KG Var"), ("KG Yok", "KG Yok"),
            ("3,5 Üst", "3,5 Üst"), ("6+ Gol", "6+ Gol"),
            ("MS 1", "MS 1"), ("MS X", "MS X"), ("MS 2", "MS 2"),
        ]:
            v = s.get(key)
            if isinstance(v, (int, float)):
                c = round(n * v / 100)
                parts.append(f"{label} {c}/{n} (%{v})")
        lines.append("Sonuç dağılımı: " + " · ".join(parts[:8]) + ".")
        iy = []
        for label in ["İY 1", "İY X", "İY 2", "2.Y 1+ Gol", "2.Y 2+ Gol", "Her iki yarı gol"]:
            v = s.get(label)
            if isinstance(v, (int, float)):
                iy.append(f"{label} %{v}")
        if iy:
            lines.append("İY / yarı: " + " · ".join(iy) + ".")
        if s.get("avg_goals") is not None:
            lines.append(f"Ortalama gol {s['avg_goals']} (ev {s.get('avg_home_goals')} / dep {s.get('avg_away_goals')}).")
        tops = s.get("top_scores") or []
        if tops:
            lines.append("Sık skor: " + ", ".join(f"{t['score']} %{t['percent']}" for t in tops[:4]) + ".")
    else:
        lines.append("Bu oran bandında sonuçlu geçmiş maç yok.")
    lines.append(f"+6 bant uyumu %{p6['compatibility_percent']} ({p6['matched_rules']}/{p6['total_rules']}).")
    bw = betwatch_find(match_title, q=q)
    bw["signals"] = money_signals(s, bw.get("overlay"), q)
    yorum = compact_yorum(s, matches, title=match_title or title, league=league, q=q, bw=bw, p6=p6)
    return {
        "title": title,
        "text": " ".join(lines),
        "sample": n,
        "stats": s,
        "plus6": p6,
        "matched": len(matches),
        "minimum_match_count": minimum,
        "pool_size": len(pool),
        "matches": matches[:limit],
        "yorum": yorum,
        "betwatch": bw,
    }


def plus6_payload(q):
    o45 = q.get("o45") if q.get("o45") is not None else q.get("g45")
    rules = [
        ("2,5 Üst", q.get("o25"), 1.20, 1.28),
        ("3,5 Üst", q.get("o35"), 1.66, 1.89),
        ("4,5 Üst / g45", o45, 2.64, 3.14),
        ("KG Var", q.get("btts"), 1.22, 1.87),
    ]
    output = []
    hit = 0
    for name, v, lo, hi in rules:
        m = v is not None and lo <= v <= hi
        hit += bool(m)
        output.append({"name": name, "value": v, "range": [lo, hi], "match": bool(m)})
    last = (q.get("iy05") is not None and 1.05 <= q["iy05"] <= 1.08) or (
        q.get("nofirst") is not None and 22.10 <= q["nofirst"] <= 26.00
    )
    if not last and q.get("g6") is not None and q["g6"] <= 9.5:
        last = True
    hit += bool(last)
    output.append({
        "name": "İY 0,5 / İlk Gol Olmaz / 6+ Gol proxy",
        "values": [q.get("iy05"), q.get("nofirst"), q.get("g6")],
        "ranges": [[1.05, 1.08], [22.10, 26.00], [None, 9.5]],
        "match": bool(last),
    })
    return {
        "matched_rules": hit,
        "total_rules": 5,
        "compatibility_percent": round(hit / 5 * 100),
        "rules": output,
    }


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
    d = q.dict() if hasattr(q, "dict") else q.model_dump()
    out = plus6_payload(d)
    note = "Yalnızca kayıtlı +6 referans bantlarıyla karşılaştırmadır. o45 yoksa g45 kullanılır."
    if HISTORY_WARNING:
        note = HISTORY_WARNING + " " + note
    out["note"] = note
    return out


@app.post("/api/brief")
def brief(req: OddsReq):
    q = {}
    for k, v in req.odds.items():
        if k not in MARKETS and k not in ("iy05", "nofirst", "o45"):
            continue
        try:
            f = float(v)
        except Exception:
            continue
        if f > 1:
            q[k] = f
    if len(q) < 2:
        raise HTTPException(400, "En az 2 oran lazım.")
    return brief_from_odds(q, req.tolerance, req.league, req.limit, title=req.title or "")
