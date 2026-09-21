from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
from collections import Counter
import json
import re
import math

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
HISTORY_FILE = DATA_DIR / "history.json"

if not HISTORY_FILE.exists():
    raise RuntimeError("data/history.json bulunamadı.")

HISTORY = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))

MARKETS = [
    "h", "d", "a",
    "u25", "o25",
    "btts", "nobtts",
    "u35", "o35",
    "iyu15", "iyo15",
    "g6"
]

app = FastAPI(title="ATASU Analiz", version="3.0.0")

static_dir = ROOT / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


# =========================================================
# HELPERS
# =========================================================

def score(value):
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(value or ""))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def stats(rows):
    z = {
        "home": 0, "draw": 0, "away": 0,
        "o15": 0, "u15": 0,
        "o25": 0, "u25": 0,
        "btts": 0, "nobtts": 0,
        "o35": 0, "u35": 0,
        "htHome": 0, "htDraw": 0, "htAway": 0,
        "fh": 0, "sh": 0, "eq": 0
    }

    n = 0
    nh = 0
    scores = Counter()
    total_goals = 0
    home_goals_sum = 0
    away_goals_sum = 0

    for r in rows:
        ft = score(r.get("ft"))
        if not ft:
            continue

        n += 1
        hg, ag = ft
        total = hg + ag
        scores[f"{hg}-{ag}"] += 1
        total_goals += total
        home_goals_sum += hg
        away_goals_sum += ag

        if hg > ag:
            z["home"] += 1
        elif hg == ag:
            z["draw"] += 1
        else:
            z["away"] += 1

        z["o15" if total >= 2 else "u15"] += 1
        z["o25" if total >= 3 else "u25"] += 1
        z["o35" if total >= 4 else "u35"] += 1
        z["btts" if hg > 0 and ag > 0 else "nobtts"] += 1

        ht = score(r.get("ht"))
        if ht:
            nh += 1
            hh, ha = ht
            if hh > ha:
                z["htHome"] += 1
            elif hh == ha:
                z["htDraw"] += 1
            else:
                z["htAway"] += 1

            first_half = hh + ha
            second_half = total - first_half
            if first_half > second_half:
                z["fh"] += 1
            elif second_half > first_half:
                z["sh"] += 1
            else:
                z["eq"] += 1

    def pct(key, denominator):
        if not denominator:
            return None
        return round(100 * z[key] / denominator, 1)

    top_scores = [
        {"score": s, "count": c, "percent": round(c / n * 100, 1)}
        for s, c in scores.most_common(5)
    ] if n else []

    return {
        "sample_ft": n,
        "sample_ht": nh,
        "avg_goals": round(total_goals / n, 2) if n else None,
        "avg_home_goals": round(home_goals_sum / n, 2) if n else None,
        "avg_away_goals": round(away_goals_sum / n, 2) if n else None,
        "top_scores": top_scores,

        "MS 1": pct("home", n),
        "MS X": pct("draw", n),
        "MS 2": pct("away", n),
        "1,5 Üst": pct("o15", n),
        "1,5 Alt": pct("u15", n),
        "2,5 Üst": pct("o25", n),
        "2,5 Alt": pct("u25", n),
        "KG Var": pct("btts", n),
        "KG Yok": pct("nobtts", n),
        "3,5 Üst": pct("o35", n),
        "3,5 Alt": pct("u35", n),
        "İY 1": pct("htHome", nh),
        "İY X": pct("htDraw", nh),
        "İY 2": pct("htAway", nh),
        "Daha çok gol 1.Y": pct("fh", nh),
        "Daha çok gol 2.Y": pct("sh", nh),
        "Yarılar eşit": pct("eq", nh)
    }


def normalize_pair(a, b):
    if a is None or b is None:
        return None
    try:
        a, b = float(a), float(b)
        if a <= 1 or b <= 1:
            return None
        ia, ib = 1 / a, 1 / b
        total = ia + ib
        return ia / total, ib / total
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def normalize_three(a, b, c):
    if any(v is None for v in (a, b, c)):
        return None
    try:
        vals = [float(a), float(b), float(c)]
        if any(v <= 1 for v in vals):
            return None
        inv = [1 / v for v in vals]
        total = sum(inv)
        return tuple(v / total for v in inv)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def poisson_pmf(k, lam):
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def poisson_over_prob(lam, line):
    threshold = int(math.floor(line)) + 1
    under_or_equal = sum(poisson_pmf(k, lam) for k in range(threshold))
    return max(0.0, min(1.0, 1.0 - under_or_equal))


def solve_lambda(target_over, line):
    lo, hi = 0.05, 8.0
    for _ in range(70):
        mid = (lo + hi) / 2
        if poisson_over_prob(mid, line) < target_over:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def build_model(odds):
    signals = []
    lambdas = []

    p25 = normalize_pair(odds.get("o25"), odds.get("u25"))
    if p25:
        po, pu = p25
        lambdas.append((solve_lambda(po, 2.5), 3.0))
        signals.append({"market": "2,5 Üst", "fair_percent": round(po * 100, 1)})

    p35 = normalize_pair(odds.get("o35"), odds.get("u35"))
    if p35:
        po, pu = p35
        lambdas.append((solve_lambda(po, 3.5), 2.0))
        signals.append({"market": "3,5 Üst", "fair_percent": round(po * 100, 1)})

    one_x_two = normalize_three(odds.get("h"), odds.get("d"), odds.get("a"))

    if lambdas:
        lam_total = sum(l * w for l, w in lambdas) / sum(w for _, w in lambdas)
    else:
        lam_total = 2.55

    if one_x_two:
        ph, pd, pa = one_x_two
        direction = (ph - pa) / max(ph + pa, 1e-9)
        share_home = max(0.18, min(0.82, 0.5 + 0.36 * direction))
    else:
        share_home = 0.5

    lam_home = max(0.05, lam_total * share_home)
    lam_away = max(0.05, lam_total - lam_home)

    grid = {}
    total_mass = 0.0
    for hg in range(11):
        for ag in range(11):
            p = poisson_pmf(hg, lam_home) * poisson_pmf(ag, lam_away)
            grid[(hg, ag)] = p
            total_mass += p

    if total_mass:
        grid = {k: v / total_mass for k, v in grid.items()}

    def gp(fn):
        return sum(p for (hg, ag), p in grid.items() if fn(hg, ag))

    model_probs = {
        "MS 1": gp(lambda h, a: h > a),
        "MS X": gp(lambda h, a: h == a),
        "MS 2": gp(lambda h, a: h < a),
        "1,5 Üst": gp(lambda h, a: h + a >= 2),
        "1,5 Alt": gp(lambda h, a: h + a <= 1),
        "2,5 Üst": gp(lambda h, a: h + a >= 3),
        "2,5 Alt": gp(lambda h, a: h + a <= 2),
        "KG Var": gp(lambda h, a: h > 0 and a > 0),
        "KG Yok": gp(lambda h, a: h == 0 or a == 0),
        "3,5 Üst": gp(lambda h, a: h + a >= 4),
        "3,5 Alt": gp(lambda h, a: h + a <= 3),
    }

    top_scores = sorted(grid.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "expected_goals": round(lam_total, 2),
        "home_xg_proxy": round(lam_home, 2),
        "away_xg_proxy": round(lam_away, 2),
        "probabilities": {k: round(v * 100, 1) for k, v in model_probs.items()},
        "top_scores": [
            {"score": f"{h}-{a}", "percent": round(p * 100, 1)}
            for (h, a), p in top_scores
        ],
        "note": "Model, girilen piyasa oranlarının marjı temizlenerek Poisson gol dağılımına kalibre edilir. xG değerleri gerçek takım xG verisi değil, piyasa-türevi gol beklentisidir."
    }


def build_consensus(history_stats, model):
    hist = history_stats or {}
    mp = model.get("probabilities", {})
    keys = [
        "MS 1", "MS X", "MS 2",
        "1,5 Üst", "1,5 Alt",
        "2,5 Üst", "2,5 Alt",
        "KG Var", "KG Yok",
        "3,5 Üst", "3,5 Alt"
    ]
    out = []

    for key in keys:
        hv = hist.get(key)
        mv = mp.get(key)
        if hv is None or mv is None:
            continue

        gap = abs(hv - mv)
        avg = (hv + mv) / 2

        if gap <= 7:
            agreement = "YÜKSEK"
        elif gap <= 14:
            agreement = "ORTA"
        else:
            agreement = "DÜŞÜK"

        out.append({
            "market": key,
            "history": hv,
            "model": mv,
            "average": round(avg, 1),
            "gap": round(gap, 1),
            "agreement": agreement
        })

    out.sort(key=lambda x: (
        {"YÜKSEK": 0, "ORTA": 1, "DÜŞÜK": 2}[x["agreement"]],
        -x["average"],
        x["gap"]
    ))
    return out


# =========================================================
# HOME / META
# =========================================================

@app.get("/")
def root():
    return FileResponse(ROOT / "index.html")


@app.get("/api/meta")
def meta():
    completed = sum(score(x.get("ft")) is not None for x in HISTORY)
    return {
        "history_rows": len(HISTORY),
        "completed_rows": completed,
        "markets": MARKETS,
        "version": "3.0.0",
        "rule": "Historical statistics use stored real match results; model probabilities are mathematical estimates derived from supplied market odds."
    }


# =========================================================
# ODDS + MODEL
# =========================================================

class OddsReq(BaseModel):
    odds: dict[str, float | None]
    tolerance: float = Field(0.05, ge=0, le=5)
    league: str = ""
    limit: int = Field(10000, ge=1, le=50000)


@app.post("/api/odds")
def odds_scan(req: OddsReq):
    q = {}
    for key, value in req.odds.items():
        if key not in MARKETS or value is None:
            continue
        try:
            q[key] = float(value)
        except (TypeError, ValueError):
            continue

    if len(q) < 2:
        raise HTTPException(status_code=400, detail="En az 2 desteklenen gerçek oran bulunmalı.")

    pool = [r for r in HISTORY if score(r.get("ft")) is not None]

    if req.league.strip():
        league_query = req.league.strip().casefold()
        pool = [r for r in pool if league_query in str(r.get("league", "")).casefold()]

    candidates = []

    for row in pool:
        differences = {}
        matched_differences = {}
        compared = 0
        matched_count = 0

        for key, target in q.items():
            historical = row.get(key)
            if historical is None:
                continue
            try:
                historical = float(historical)
            except (TypeError, ValueError):
                continue

            compared += 1
            diff = abs(historical - target)
            differences[key] = round(diff, 3)

            if diff <= req.tolerance:
                matched_count += 1
                matched_differences[key] = round(diff, 3)

        if compared < 2:
            continue

        item = dict(row)
        item["_matched_odds"] = matched_count
        item["_compared_odds"] = compared
        item["_match_ratio"] = round(matched_count / compared * 100, 1)
        item["_differences"] = differences
        item["_matched_differences"] = matched_differences
        item["_total_difference"] = round(sum(differences.values()), 3)
        candidates.append(item)

    searched_count = len(q)
    minimum_match_count = max(2, (searched_count + 1) // 2)

    matches = [x for x in candidates if x["_matched_odds"] >= minimum_match_count]
    fallback = False

    if not matches and candidates:
        best_match_count = max(x["_matched_odds"] for x in candidates)
        if best_match_count > 0:
            matches = [x for x in candidates if x["_matched_odds"] == best_match_count]
            fallback = True

    matches.sort(key=lambda x: (
        -x["_matched_odds"],
        -x["_match_ratio"],
        x["_total_difference"]
    ))

    total_matches = len(matches)
    returned_matches = matches[:req.limit]
    best_match_count = matches[0]["_matched_odds"] if matches else 0
    historical_stats = stats(matches)
    model = build_model(q)
    consensus = build_consensus(historical_stats, model)

    if fallback:
        method = (
            f"{searched_count} oran tarandı. En güçlü gerçek eşleşmeler gösteriliyor. "
            f"En yüksek eşleşme: {best_match_count}/{searched_count}."
        )
    else:
        method = (
            f"{searched_count} oran tarandı. En az {minimum_match_count}/{searched_count} oranı "
            f"±{req.tolerance} içinde eşleşen maçlar gösteriliyor. "
            f"En güçlü eşleşme: {best_match_count}/{searched_count}."
        )

    return {
        "method": method,
        "searched_odds": q,
        "searched_count": searched_count,
        "tolerance": req.tolerance,
        "pool_size": len(pool),
        "matched": total_matches,
        "returned": len(returned_matches),
        "minimum_match_count": minimum_match_count,
        "best_match_count": best_match_count,
        "stats": historical_stats,
        "model": model,
        "consensus": consensus,
        "matches": returned_matches
    }


# =========================================================
# +6 ANALYSIS
# =========================================================

class Plus6Req(BaseModel):
    o25: float | None = None
    o35: float | None = None
    o45: float | None = None
    btts: float | None = None
    iy05: float | None = None
    nofirst: float | None = None


@app.post("/api/plus6")
def plus6(q: Plus6Req):
    rules = [
        ("2,5 Üst", q.o25, 1.20, 1.28),
        ("3,5 Üst", q.o35, 1.66, 1.89),
        ("4,5 Üst", q.o45, 2.64, 3.14),
        ("KG Var", q.btts, 1.22, 1.87)
    ]

    output = []
    hit = 0

    for name, value, lo, hi in rules:
        matched = value is not None and lo <= value <= hi
        if matched:
            hit += 1
        output.append({
            "name": name,
            "value": value,
            "range": [lo, hi],
            "match": matched
        })

    last = (
        (q.iy05 is not None and 1.05 <= q.iy05 <= 1.08)
        or
        (q.nofirst is not None and 22.10 <= q.nofirst <= 26.00)
    )

    if last:
        hit += 1

    output.append({
        "name": "İY 0,5 Üst veya İlk Gol Olmaz",
        "values": [q.iy05, q.nofirst],
        "ranges": [[1.05, 1.08], [22.10, 26.00]],
        "match": last
    })

    return {
        "matched_rules": hit,
        "total_rules": 5,
        "compatibility_percent": round(hit / 5 * 100),
        "rules": output,
        "note": "Bu bölüm yalnızca kayıtlı +6 referans bantlarıyla karşılaştırmadır."
    }
