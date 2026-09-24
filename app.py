from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
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
from mackolik_standing import (
    resolve_match as mk_resolve_match,
    standing_lines as mk_standing_lines,
    analysis_lines as mk_analysis_lines,
    score_open_picks,
    tercih_from_open,
    open_markets,
)
from updater import run_update, remember_season, _load_state
from extra_feeds import lookup as fd_lookup
from pipeline import build_pipeline, lines_from_pipeline
from banko import evaluate as banko_evaluate, lines as banko_lines
try:
    from ai_coach import compose as coach_compose
except Exception:
    coach_compose = None


def _standing(home, away="", league=""):
    pack = mk_resolve_match(home, away, league)
    if pack and pack.get("season_id"):
        remember_season(pack["season_id"])
    try:
        extra = fd_lookup(home or "", away or "", league or "")
    except Exception as e:
        extra = {"ok": False, "note": str(e)[:80], "source": "football-data.co.uk"}
    if pack is None:
        pack = {"ok": False, "home": home, "away": away}
    pack["extra"] = extra
    try:
        pack["pipeline"] = build_pipeline(
            home or "", away or "", standing=pack, extra=extra, league=league or ""
        )
    except Exception as e:
        pack["pipeline"] = {"ok": False, "note": str(e)[:80]}
    an = pack.setdefault("analysis", {})
    if extra.get("ok"):
        if an.get("combo_o25") is None and extra.get("combo_o25") is not None:
            an["combo_o25"] = extra["combo_o25"]
        if an.get("combo_kg") is None and extra.get("combo_kg") is not None:
            an["combo_kg"] = extra["combo_kg"]
        flags = an.setdefault("flags", [])
        bits = []
        if extra.get("league_o25") is not None:
            bits.append(f"fd lig 2.5Ü %{extra['league_o25']}")
        if extra.get("league_kg") is not None:
            bits.append(f"fd lig KG %{extra['league_kg']}")
        if extra.get("combo_o25") is not None:
            bits.append(f"fd form 2.5Ü %{extra['combo_o25']}")
        if bits:
            flags.append(" · ".join(bits))
    return pack


app = FastAPI(title="ATASU Intelligence", version="5.5.0")
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


CORE_KEYS = ("h", "d", "a", "o25", "u25", "btts")


def match_rows(q, tol, league=""):
    pool = [r for r in HISTORY if score(r.get("ft")) is not None]
    lig = league.strip()
    lig_pool = pool
    if lig:
        folded = lig.casefold()
        lig_pool = [r for r in pool if folded in str(r.get("league", "")).casefold()]
        # Lig kodu history ile uyuşmazsa havuzu öldürme
        if len(lig_pool) < 80:
            lig_pool = pool
    p_tol = max(0.012, min(0.12, tol / 2.5))
    core_q = {k: v for k, v in q.items() if k in CORE_KEYS}

    def score_pool(src, use_q, use_tol, use_ptol, min_hit):
        out = []
        for r in src:
            diffs = {}; pgaps = {}; compared = matched = 0
            wsum = wscore = 0.0
            for k, target in use_q.items():
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
                hit = d <= use_tol or (g is not None and g <= use_ptol)
                matched += int(hit)
                w = WEIGHTS.get(k, 0.7)
                wsum += w
                denom = max(use_ptol * 3, 1e-6)
                closeness = 1.0 - min(1.0, (g if g is not None else d / max(target, 1)) / denom)
                wscore += w * max(0.0, closeness)
            if compared < 2:
                continue
            if matched < min_hit:
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
        out.sort(key=lambda x: (-x["_similarity"], -x["_matched_odds"], x["_total_difference"]))
        return out

    # 1) çekirdek piyasalar, verilen tol
    minimum = 2
    matches = score_pool(lig_pool, core_q or q, tol, p_tol, 2)
    fallback = False
    # 2) genişlet
    if len(matches) < 12:
        wider = score_pool(lig_pool, core_q or q, max(tol, 0.12), max(p_tol, 0.04), 2)
        if len(wider) > len(matches):
            matches, fallback = wider, True
    # 3) tüm havuz + 1X2 yakınlığı
    if len(matches) < 8:
        ms_q = {k: v for k, v in q.items() if k in ("h", "d", "a")}
        if len(ms_q) >= 2:
            soft = score_pool(pool, ms_q, 0.18, 0.05, 2)
            if soft:
                matches, fallback = soft, True
                minimum = 2
    return pool, matches, minimum, fallback


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


def dixon_coles(lh, la, rho=-0.13, nmax=8):
    """Bivariate Poisson + DC low-score correction. rho typical -0.10..-0.15."""
    if not lh or not la:
        return None
    lh = max(0.12, float(lh))
    la = max(0.12, float(la))
    rho = float(rho)

    def tau(h, a):
        if h == 0 and a == 0:
            return 1 - lh * la * rho
        if h == 0 and a == 1:
            return 1 + lh * rho
        if h == 1 and a == 0:
            return 1 + la * rho
        if h == 1 and a == 1:
            return 1 - rho
        return 1.0

    cells = []
    p_h = p_d = p_a = p_o25 = p_u25 = p_o35 = p_btts = p_g6 = p_ht_proxy = 0.0
    tot = 0.0
    for h in range(0, nmax + 1):
        ph = poisson_pmf(h, lh)
        for a in range(0, nmax + 1):
            pa = poisson_pmf(a, la)
            p = max(0.0, ph * pa * tau(h, a))
            tot += p
            cells.append((h, a, p))
    if tot <= 0:
        return None
    scores = []
    for h, a, p in cells:
        p = p / tot
        t = h + a
        if h > a:
            p_h += p
        elif h == a:
            p_d += p
        else:
            p_a += p
        if t >= 3:
            p_o25 += p
        else:
            p_u25 += p
        if t >= 4:
            p_o35 += p
        if h and a:
            p_btts += p
        if t >= 6:
            p_g6 += p
        scores.append({"score": f"{h}-{a}", "percent": round(p * 100, 2)})
    scores.sort(key=lambda x: -x["percent"])
    # implied no-vig from 1X2 if later mixed; here model probs
    return {
        "lambda_home": round(lh, 2),
        "lambda_away": round(la, 2),
        "rho": rho,
        "ms1": round(p_h * 100, 1),
        "msx": round(p_d * 100, 1),
        "ms2": round(p_a * 100, 1),
        "p_o25": round(p_o25 * 100, 1),
        "p_u25": round(p_u25 * 100, 1),
        "p_o35": round(p_o35 * 100, 1),
        "p_u35": round((1 - p_o35) * 100, 1),
        "p_btts": round(p_btts * 100, 1),
        "p_g6": round(p_g6 * 100, 1),
        "top": scores[:8],
        "fair_odds": {
            "h": round(1 / p_h, 2) if p_h > 0.02 else None,
            "d": round(1 / p_d, 2) if p_d > 0.02 else None,
            "a": round(1 / p_a, 2) if p_a > 0.02 else None,
            "o25": round(1 / p_o25, 2) if p_o25 > 0.02 else None,
            "u25": round(1 / p_u25, 2) if p_u25 > 0.02 else None,
            "btts": round(1 / p_btts, 2) if p_btts > 0.02 else None,
        },
        "note": "Dixon-Coles. rho=-0.13 düşük skor bağımlılığı. 1M MC değil, tam ızgara.",
    }


def no_vig_group(odds_map):
    """Normalize a mutually exclusive group to 100%."""
    items = []
    s = 0.0
    for k, o in odds_map.items():
        p = implied(o)
        if not p:
            continue
        items.append((k, o, p))
        s += p
    if s <= 0:
        return []
    out = []
    for k, o, p in items:
        nv = p / s
        out.append({
            "key": k,
            "name": NAMES.get(k, k),
            "odds": o,
            "raw_percent": round(p * 100, 1),
            "no_vig_percent": round(nv * 100, 1),
            "fair_odds": round(1 / nv, 2) if nv > 0 else None,
            "margin_share": round((p - nv) * 100, 2),
        })
    return out


def consensus_lambda(q, stats_obj=None, standing=None):
    """Tek λ ev/dep: tablo + football-data form + oran + kalıp. Hepsi aynı DC'ye gider."""
    stats_obj = stats_obj or {}
    standing = standing or {}
    an = standing.get("analysis") or {}
    extra = standing.get("extra") or {}
    cands_h, cands_a = [], []

    if an.get("exp_home") and an.get("exp_away"):
        cands_h.append((float(an["exp_home"]), 1.3))
        cands_a.append((float(an["exp_away"]), 1.3))
    hf, af = extra.get("home_form") or {}, extra.get("away_form") or {}
    if hf.get("gf_pg") is not None and af.get("gf_pg") is not None:
        # ev gol atışı ev sahada, dep gol atışı dışarıda — kaba
        cands_h.append((0.65 * float(hf["gf_pg"]) + 0.35 * float(af.get("ga_pg") or hf["gf_pg"]), 1.0))
        cands_a.append((0.65 * float(af["gf_pg"]) + 0.35 * float(hf.get("ga_pg") or af["gf_pg"]), 1.0))
    lam_odds = expected_goals(q)
    share = 0.55
    if q.get("h") and q.get("a"):
        ph, pa = implied(q["h"]) or 0.4, implied(q["a"]) or 0.3
        share = 0.5 + 0.28 * ((ph - pa) / max(ph + pa, 0.05))
        share = min(0.76, max(0.24, share))
    if lam_odds:
        cands_h.append((lam_odds * share, 0.9))
        cands_a.append((lam_odds * (1 - share), 0.9))
    if stats_obj.get("avg_goals"):
        ag = float(stats_obj["avg_goals"])
        hs = stats_obj.get("avg_home_goals")
        if hs:
            cands_h.append((float(hs), 0.6))
            cands_a.append((max(0.2, ag - float(hs)), 0.6))
        else:
            cands_h.append((ag * share, 0.5))
            cands_a.append((ag * (1 - share), 0.5))

    def blend(cands, default):
        if not cands:
            return default
        num = sum(v * w for v, w in cands)
        den = sum(w for _, w in cands)
        return max(0.20, min(3.40, num / den))

    lh = blend(cands_h, 1.35)
    la = blend(cands_a, 1.15)
    return {
        "lambda_home": round(lh, 2),
        "lambda_away": round(la, 2),
        "lambda_total": round(lh + la, 2),
        "sources": len(cands_h),
        "share": round(share, 3),
    }


def lh_style_engine(q, stats_obj=None, standing=None):
    """Tek konsensüs λ → tek Dixon-Coles. Katmanlar ayrı yüzde basmaz."""
    stats_obj = stats_obj or {}
    cons = consensus_lambda(q, stats_obj, standing)
    lh, la = cons["lambda_home"], cons["lambda_away"]
    if not lh or not la:
        return {"ok": False, "reason": "λ yok", "consensus": cons}
    dc = dixon_coles(lh, la)
    groups = []
    for keys in (["h", "d", "a"], ["u25", "o25"], ["btts", "nobtts"], ["u35", "o35"]):
        sub = {k: q[k] for k in keys if q.get(k)}
        if len(sub) >= 2:
            groups.append(no_vig_group(sub))
    edges = []
    model_p = {
        "h": dc["ms1"] if dc else None,
        "d": dc["msx"] if dc else None,
        "a": dc["ms2"] if dc else None,
        "o25": dc["p_o25"] if dc else None,
        "u25": dc["p_u25"] if dc else None,
        "btts": dc["p_btts"] if dc else None,
        "o35": dc.get("p_o35") if dc else None,
        "u35": dc.get("p_u35") if dc else None,
    }
    for k, mp in model_p.items():
        if mp is None or not q.get(k):
            continue
        p = mp / 100.0
        ev = round(p * q[k] - 1, 3)
        if ev >= 0.08 and mp >= 28 and q[k] <= 3.2:
            sig = "AL"
        elif ev <= -0.08 and mp <= 55:
            sig = "PAHALI"
        else:
            sig = "nötr"
        edges.append({
            "key": k,
            "name": NAMES.get(k, k),
            "model_percent": mp,
            "odds": q[k],
            "ev_percent": round(ev * 100, 1),
            "kelly_half": kelly_fraction(p, q[k]) and round(kelly_fraction(p, q[k]) / 2, 4),
            "signal": sig,
        })
    edges.sort(key=lambda x: x["ev_percent"], reverse=True)
    return {
        "ok": True,
        "lambda_total": cons["lambda_total"],
        "lambda_home": cons["lambda_home"],
        "lambda_away": cons["lambda_away"],
        "consensus": cons,
        "dixon_coles": dc,
        "no_vig": groups,
        "edges": edges,
        "top_model": (dc["top"][0] if dc and dc.get("top") else None),
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
# LH Bet sekmesi kaldirildi

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


TEAM_ALIAS = {
    "japonya": "japan", "tayland": "thailand", "turkiye": "turkey", "almanya": "germany",
    "fransa": "france", "ingiltere": "england", "ispanya": "spain", "italya": "italy",
    "portekiz": "portugal", "hollanda": "netherlands", "belcika": "belgium",
    "isvicre": "switzerland", "avusturya": "austria", "isvec": "sweden", "norvec": "norway",
    "danimarka": "denmark", "polonya": "poland", "cekya": "czech", "cek": "czech",
    "yunanistan": "greece", "hirvatistan": "croatia", "sirbistan": "serbia",
    "romanya": "romania", "macaristan": "hungary", "ukrayna": "ukraine",
    "rusya": "russia", "cin": "china", "guney kore": "south korea", "kore": "korea",
    "suudi arabistan": "saudi arabia", "bae": "uae", "misir": "egypt",
    "fas": "morocco", "cezayir": "algeria", "tunus": "tunisia", "nijerya": "nigeria",
    "brezilya": "brazil", "arjantin": "argentina", "meksika": "mexico",
    "abd": "usa", "amerika": "usa", "avustralya": "australia",
    "yeni zelanda": "new zealand", "guney afrika": "south africa",
    "kirgizistan": "kyrgyzstan", "hong kong": "hong kong", "hongkong": "hong kong",
    "ozbekistan": "uzbekistan", "kazakistan": "kazakhstan", "turkmenistan": "turkmenistan",
    "azerbaycan": "azerbaijan", "gurcistan": "georgia", "ermeninistan": "armenia",
    "irak": "iraq", "iran": "iran", "suriye": "syria", "filistin": "palestine",
    "israil": "israel", "katar": "qatar", "kuveyt": "kuwait", "umman": "oman",
    "endonezya": "indonesia", "malezya": "malaysia", "vietnam": "vietnam",
    "real madrid": "real madrid", "getafe": "getafe",
}


def _norm_team(s):
    s = (s or "").casefold()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = s.replace("ü", "u").replace("ö", "o").replace("ş", "s").replace("ç", "c").replace("ı", "i").replace("ğ", "g")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(u1[89]|u2[013]|u23|u21|u19|u18|u17)\b", "u23" if "u23" in s or "u21" in s else "u", s)
    for tr, en in TEAM_ALIAS.items():
        if tr in s:
            s = s.replace(tr, en)
    drop = {"fc", "cf", "sk", "fk", "afc", "sc", "the", "de", "united", "city", "w", "u", "u18", "u19", "u21", "u23"}
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
    inter = sa & sb
    if len(inter) >= 1 and any(len(x) >= 3 for x in inter):
        return 2
    if inter:
        return 1
    # prefix 5+
    for x in sa:
        for y in sb:
            if len(x) >= 5 and len(y) >= 5 and (x.startswith(y[:5]) or y.startswith(x[:5])):
                return 2
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
    title_n = _norm_team(title or "")
    scored = []
    for m in pool:
        sc = _team_hit(home, m["home"]) + _team_hit(away, m["away"])
        if sc <= 0 and home:
            sc = _team_hit(home, m["home"]) + _team_hit(home, m["away"])
        pair_n = _norm_team(f"{m.get('home')} {m.get('away')}")
        if title_n and pair_n:
            ta, tb = set(title_n.split()), set(pair_n.split())
            inter = {x for x in (ta & tb) if len(x) >= 4}
            if len(inter) >= 2:
                sc = max(sc, 4)
            elif len(inter) == 1:
                sc = max(sc, 2)
        if sc <= 0:
            continue
        scored.append((sc, m))
    scored.sort(key=lambda x: -x[0])
    best = None
    if scored:
        if scored[0][0] >= 2:
            best = scored[0][1]
        elif scored[0][0] >= 1 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
            best = scored[0][1]
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
        "lh_url": None,
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
        "version": "5.5.0",
        "warning": HISTORY_WARNING,
        "rule": "Yalnızca history.json içindeki gerçek oran ve sonuçlar kullanılır. Puan durumu Maçkolik arşivinden çekilir.",
        "ledger": (ROOT / "data" / "ledger.json").exists(),
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


class MacIdReq(BaseModel):
    mac_id: str
    title: str = ""


@app.post("/api/from-mac")
def from_mac(req: MacIdReq):
    mac_id = re.sub(r"\D", "", req.mac_id or "")
    if len(mac_id) < 5:
        raise HTTPException(400, "Geçerli mac_id yok")
    try:
        raw = _fetch(f"https://arsiv.mackolik.com/AjaxHandlers/IddaaHandler.aspx?command=morebets&mac={mac_id}&type=ByLeague")
        name, bulletin = _morebets_bulletin(raw)
        title = (req.title or name or "").strip()
        if not bulletin or len(bulletin) < 20:
            raise ValueError("bülten boş")
        home, away = _parse_teams(title)
        return {
            "ok": True,
            "mac_id": mac_id,
            "title": title,
            "home": home,
            "away": away,
            "text": bulletin,
            "source": "Mackolik Iddaa",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, "Maç bülteni alınamadı: " + str(e)[:120])


@app.get("/api/selftest")
def selftest():
    return {
        "ok": True,
        "version": "5.5.0",
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
    ev_name, dep_name = _parse_teams(req.title or "")
    standing = None
    try:
        standing = _standing(ev_name or "", dep_name or "", req.league or "")
    except Exception:
        standing = None
    lh = lh_style_engine(q, s, standing)
    yorum = compact_yorum(
        s, matches, title=req.title or "", league=req.league or "", q=q, bw=bw, p6=p6, lh=lh, standing=standing,
    )
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
        "lh_model": lh,
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


def exact_equal(a, b, band=0.03):
    try:
        fa, fb = float(a), float(b)
        if fa == fb:
            return True
        if abs(fa - fb) <= band:
            return True
        g = prob_gap(fa, fb)
        return g is not None and g <= 0.012
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
            "status": "EŞLEŞME VAR" if rows else "YAKIN EŞLEŞME YOK",
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


def _pct(v):
    return None if not isinstance(v, (int, float)) else v


def _ima_pct(odd):
    try:
        o = float(odd)
        return round(100.0 / o, 1) if o > 1 else None
    except Exception:
        return None


def narrative_yorum(s, matches, title="", league="", q=None, bw=None, p6=None, lh=None, standing=None):
    """Tek parça analist yorumu — iddaa açık oranları merkeze alır."""
    q = q or {}
    n = s.get("sample_ft") or 0
    head = (title.split("|")[0].strip() if title else "Maç")
    dc = ((lh or {}).get("dixon_coles") or {}) if lh else {}
    an = ((standing or {}).get("analysis") or {}) if standing else {}
    hr = ((standing or {}).get("home_row") or {}) if standing else {}
    ar = ((standing or {}).get("away_row") or {}) if standing else {}
    ranked = score_open_picks(q, s, lh, standing)
    tercih = tercih_from_open(ranked, n)

    def g(name):
        v = s.get(name)
        return v if isinstance(v, (int, float)) else None

    o25_h, kg_h, ms1, msx, ms2 = g("2,5 Üst"), g("KG Var"), g("MS 1"), g("MS X"), g("MS 2")
    o35_h, sh = g("3,5 Üst"), g("2.Y 1+ Gol")
    avg = s.get("avg_goals")

    ev_n = hr.get("name") or ""
    dep_n = ar.get("name") or ""
    mas = head.rstrip(".")
    p1 = []
    ac = []
    if ev_n and dep_n:
        ac.append(f"{ev_n}–{dep_n}")
    else:
        ac.append(mas)
    if hr and ar and hr.get("pos") and ar.get("pos"):
        ac.append(
            f"ligde {hr['pos']}. ({hr.get('pts')}p, {hr.get('gf')}-{hr.get('ga')}) "
            f"× {ar['pos']}. ({ar.get('pts')}p, {ar.get('gf')}-{ar.get('ga')})"
        )
    if an.get("exp_total") is not None:
        ac.append(f"taraf temposu {an['exp_home']}+{an['exp_away']} ≈ {an['exp_total']} gol")
    hop, aop = an.get("home_opta") or {}, an.get("away_opta") or {}
    if hop and aop:
        ac.append(
            f"şut profili {hop.get('shots_pg')}/{hop.get('sot_pg')} vs {aop.get('shots_pg')}/{aop.get('sot_pg')}, "
            f"TSO %{hop.get('possession')}–%{aop.get('possession')}"
        )
    if an.get("combo_o25") is not None or an.get("combo_kg") is not None:
        ac.append(
            "ev sahada / deplasmanda "
            + (f"2.5Ü %{an.get('combo_o25')}" if an.get("combo_o25") is not None else "")
            + (" · " if an.get("combo_o25") is not None and an.get("combo_kg") is not None else "")
            + (f"KG %{an.get('combo_kg')}" if an.get("combo_kg") is not None else "")
        )
    if an.get("flags"):
        ac.append(", ".join(an["flags"]))
    p1.append("Maç: " + "; ".join(ac) + ".")

    # 2. İddaa fiyatı vs okuma
    p2 = []
    checks = [
        ("h", "MS 1", ms1, dc.get("ms1")),
        ("a", "MS 2", ms2, dc.get("ms2")),
        ("d", "MS X", msx, dc.get("msx")),
        ("o25", "2,5 Üst", o25_h, dc.get("p_o25")),
        ("o35", "3,5 Üst", o35_h, None),
        ("btts", "KG Var", kg_h, dc.get("p_btts")),
    ]
    pahali, ucuz, kisa = [], [], []
    for key, lab, hist, model in checks:
        if key not in q:
            continue
        odd = q[key]
        ima = _ima_pct(odd)
        okuma = None
        if isinstance(hist, (int, float)) and isinstance(model, (int, float)):
            okuma = round(0.55 * hist + 0.45 * model, 1)
        elif isinstance(hist, (int, float)):
            okuma = hist
        elif isinstance(model, (int, float)):
            okuma = model
        if ima is None:
            continue
        if odd < 1.40:
            kisa.append(f"{lab} {odd} (iddaa ima %{ima}" + (f", okuma %{okuma}" if okuma is not None else "") + ")")
        elif okuma is not None and okuma <= ima - 8:
            pahali.append(f"{lab} {odd} ima %{ima} / okuma %{okuma}")
        elif okuma is not None and okuma >= ima + 8:
            ucuz.append(f"{lab} {odd} ima %{ima} / okuma %{okuma}")
    if q.get("a") and q.get("h") and q["a"] < q["h"]:
        p2.append(
            f"İddaa bu maçı deplasman favorisi satıyor (MS 2 {q['a']}, ima %{_ima_pct(q['a'])}; "
            f"MS 1 {q['h']}, ima %{_ima_pct(q['h'])})."
        )
    elif q.get("h") and q.get("a"):
        p2.append(
            f"İddaa ev favorisi satıyor (MS 1 {q['h']}, ima %{_ima_pct(q['h'])}; "
            f"MS 2 {q['a']}, ima %{_ima_pct(q['a'])})."
        )
    if n:
        p2.append(
            f"Aynı fiyat bandındaki {n} sonuç bunu doğrulamıyor: "
            f"MS {ms1}/{msx}/{ms2}, 2.5Ü %{o25_h}, 3.5Ü %{o35_h}, KG %{kg_h}, "
            f"2. yarı gol %{sh}"
            + (f", ortalama {avg}." if avg else ".")
        )
    else:
        p2.append("History bu fiyatı henüz yakalamadı; masa modeli ve tabloya bakıyor.")
    if dc.get("ms1") is not None:
        p2.append(
            f"Poisson/Dixon-Coles λ {dc.get('lambda_home')}–{dc.get('lambda_away')} → "
            f"MS {dc.get('ms1')}–{dc.get('msx')}–{dc.get('ms2')}, 2.5Ü %{dc.get('p_o25')}, KG %{dc.get('p_btts')}."
        )
    if kisa:
        p2.append("Kısa iddaa fiyatı (kenar yok, birim şişirme): " + "; ".join(kisa) + ".")
    if pahali:
        p2.append("Pahalı açık iş — kupon dışı: " + "; ".join(pahali) + ".")
    if ucuz:
        p2.append("Masanın ucuz bıraktığı açık iş: " + "; ".join(ucuz) + ".")
    if not kisa and not pahali and not ucuz:
        p2.append("Açık fiyatlar adil; burada edge avlanmaz.")

    # 3. Para / +6 kısa
    p3 = []
    if bw and bw.get("matched"):
        m = bw["matched"]
        p3.append(f"Exchange eşleşti: {m.get('home')}–{m.get('away')}.")
    elif title:
        p3.append("Exchange bu isimle açılmadı; kuponu teyit etmez.")
    if p6 and p6.get("compatibility_percent") is not None:
        pc = p6.get("compatibility_percent")
        if pc >= 70:
            p3.append(f"+6 bandı uyumlu (%{pc}).")
        elif pc <= 35:
            p3.append(f"+6 senaryosu değil (%{pc}).")

    lines = [" ".join(p1), "", " ".join(p2)]
    if p3:
        lines += ["", " ".join(p3)]
    lines += ["", "[[ATASU_TERCIH]]"]
    lines.extend(tercih[:6])
    lines.append("[[/ATASU_TERCIH]]")
    return "\n".join(lines)


def compact_yorum(s, matches, title="", league="", q=None, bw=None, p6=None, lh=None, standing=None):
    return narrative_yorum(s, matches, title, league, q, bw, p6, lh, standing)
    q = q or {}
    n = s.get("sample_ft") or 0
    ev, dep = _parse_teams(title)
    ligler = Counter(str(r.get("league") or "?") for r in matches)
    lig_txt = ", ".join(f"{k} ({v})" for k, v in ligler.most_common(4))
    head = (title.split("|")[0].strip() if title else "Maç özeti")
    lines = [head]
    if league:
        lines.append("Lig filtresi: " + league)

    if standing and standing.get("ok"):
        lines.append(
            "Mackolik tablo: "
            + (standing.get("season_label") or "")
            + (f" (sezon {standing.get('season_id')})" if standing.get("season_id") else "")
        )
        hs = mk_standing_lines(standing, "home")
        ds = mk_standing_lines(standing, "away")
        if hs:
            lines.append("Ev " + " · ".join(hs))
        if ds:
            lines.append("Dep " + " · ".join(ds))
        for ln in mk_analysis_lines(standing):
            lines.append(ln)
    elif standing and standing.get("note"):
        lines.append("Mackolik tablo: " + standing["note"])

    if not n:
        lines.append("Benzer oranlı sonuçlu maç bulunamadı. Sadece piyasa, tablo ve model konuşur.")
        if lh and lh.get("ok") and lh.get("dixon_coles"):
            dc = lh["dixon_coles"]
            lines.append(
                f"Dixon-Coles modele göre ev {dc.get('ms1')}%, beraberlik {dc.get('msx')}%, deplasman {dc.get('ms2')}%. "
                f"2.5 üst {dc.get('p_o25')}%, KG {dc.get('p_btts')}%."
            )
        if bw and not bw.get("matched"):
            lines.append("Betfair Exchange bu isimle maç açmamış veya eşleşmedi.")
        ranked = score_open_picks(q, s, lh, standing)
        lines.append("Açık iddaa piyasaları: " + (", ".join(f"{n} {o}" for _, n, o in open_markets(q)) or "yok") + ".")
        tercih = tercih_from_open(ranked, 0)
        lines.append("Karar: örnek yok. Tercih yalnızca açık oranlardan.")
        lines.append("")
        lines.append("[[ATASU_TERCIH]]")
        lines.extend(tercih[:6])
        lines.append("[[/ATASU_TERCIH]]")
        return "\n".join(lines)

    p1, px, p2 = _pct(s.get("MS 1")) or 0, _pct(s.get("MS X")) or 0, _pct(s.get("MS 2")) or 0
    o25, u25 = _pct(s.get("2,5 Üst")) or 0, _pct(s.get("2,5 Alt")) or 0
    o35 = _pct(s.get("3,5 Üst")) or 0
    kg = _pct(s.get("KG Var")) or 0
    iy1 = _pct(s.get("İY 1"))
    sh1 = _pct(s.get("2.Y 1+ Gol"))
    tops = s.get("top_scores") or []
    lider, lp = max([("ev", p1), ("beraberlik", px), ("deplasman", p2)], key=lambda x: x[1])

    lines.append("")
    lines.append("1) Geçmiş benzer maçlar (Excel eşleşme)")
    lines.append(
        f"Aynı oran bandında {n} sonuçlu maç var"
        + (f"; lig dağılımı: {lig_txt}." if lig_txt else ".")
        + (" Örnek 30'un altında, yüzdeler kırılgan." if n < 30 else " Örnek yeterli.")
    )
    lines.append(
        f"Maç sonu: ev %{p1:.0f}, beraberlik %{px:.0f}, deplasman %{p2:.0f}. "
        f"İlk yarı ev %{iy1:.0f}." if iy1 is not None else
        f"Maç sonu: ev %{p1:.0f}, beraberlik %{px:.0f}, deplasman %{p2:.0f}."
    )
    if tops:
        lines.append("Sık bitişler: " + ", ".join(f"{t['score']} (%{t['percent']:.0f})" for t in tops[:4]) + ".")
    gol_txt = f"Ortalama {s.get('avg_goals')} gol (ev {s.get('avg_home_goals')} / dep {s.get('avg_away_goals')}). " if s.get("avg_goals") is not None else ""
    lines.append(
        gol_txt + f"2.5 üst %{o25:.0f}, 3.5 üst %{o35:.0f}, KG %{kg:.0f}"
        + (f", ikinci yarıda gol %{sh1:.0f}." if sh1 is not None else ".")
    )
    fe = _team_form(ev) if ev else None
    fd = _team_form(dep) if dep else None
    if fe or fd:
        form_l = []
        if fe:
            form_l.append(f"{fe['ad']} son {fe['n']} maç {fe['WDL']} (gol {fe['ort']}, form {fe['form']})")
        if fd:
            form_l.append(f"{fd['ad']} son {fd['n']} maç {fd['WDL']} (gol {fd['ort']}, form {fd['form']})")
        lines.append("Kendi havuz form: " + " | ".join(form_l) + ".")
    preview = (standing or {}).get("table_preview") or []
    if preview:
        lines.append(
            "Üst sıra: "
            + ", ".join(f"{r['pos']}.{r['name']} {r['pts']}p" for r in preview[:5])
            + "."
        )

    lines.append("")
    lines.append("2) Piyasa oranları")
    book_bits = []
    for k, name in [("h", "MS 1"), ("d", "MS X"), ("a", "MS 2"), ("o25", "2.5 üst"), ("u25", "2.5 alt"), ("btts", "KG var"), ("nobtts", "KG yok"), ("o35", "3.5 üst")]:
        if q.get(k):
            ip = implied(q[k])
            book_bits.append(f"{name} {q[k]}" + (f" (ima %{ip*100:.0f})" if ip else ""))
    if book_bits:
        lines.append("İddaa/girilen oran: " + "; ".join(book_bits) + ".")
    else:
        lines.append("Bu tarama için oran kutusu boş.")

    lines.append("")
    lines.append("3) Betfair para (Betwatch)")
    matched_bw = (bw or {}).get("matched")
    if not BETWATCH_TOKEN:
        lines.append("Betfair bağlı değil (anahtar yok). Para teyidi bu maçta yok.")
    elif not matched_bw:
        lines.append("Bu maç Betfair Exchange'de yok veya isim eşleşmedi. Küçük / gençlik liglerinde normal.")
    else:
        lines.append(f"Eşleşen market: {matched_bw.get('home')} - {matched_bw.get('away')} ({matched_bw.get('source')}).")
        money_lines = []
        for key, label in [("h", "MS 1"), ("d", "MS X"), ("a", "MS 2"), ("o25", "2.5 üst"), ("u25", "2.5 alt"), ("btts", "KG var")]:
            mk = (matched_bw.get("markets") or {}).get(key) or {}
            if mk.get("odd") is None and mk.get("money_pct") is None:
                continue
            piece = label
            if mk.get("odd"):
                piece += f" oran {mk['odd']}"
            if mk.get("money_pct") is not None:
                piece += f", paranın %{mk['money_pct']:.0f}'i"
            if mk.get("volume"):
                piece += f" (€{int(mk['volume'])})"
            money_lines.append(piece)
        if money_lines:
            lines.append("Para dağılımı: " + "; ".join(money_lines) + ".")
        else:
            lines.append("Market açık ama volume henüz düşük.")

    lines.append("")
    lines.append("4) Dixon-Coles model")
    if lh and lh.get("ok") and lh.get("dixon_coles"):
        dc = lh["dixon_coles"]
        top = (dc.get("top") or [{}])[0]
        lines.append(
            f"λ ev {dc.get('lambda_home')} / λ dep {dc.get('lambda_away')}. "
            f"Model MS: ev %{dc.get('ms1')}, X %{dc.get('msx')}, dep %{dc.get('ms2')}. "
            f"2.5 üst %{dc.get('p_o25')}, KG %{dc.get('p_btts')}. "
            f"En olası skor {top.get('score')} (%{top.get('percent')})."
        )
        strong = [x for x in (lh.get("edges") or []) if x.get("signal") in ("AL", "PAHALI")]
        if strong:
            lines.append("Modele göre değer: " + "; ".join(
                f"{x['name']} EV %{x['ev_percent']} ({x['signal']})" for x in strong[:4]
            ) + ".")
    else:
        lines.append("Model λ üretemedi (2.5/3.5 oranı veya ortalama gol yok).")

    if p6:
        lines.append("")
        lines.append("5) +6 bandı")
        lines.append(
            f"+6 uyumu %{p6.get('compatibility_percent')} ({p6.get('matched_rules')}/{p6.get('total_rules')} kural). "
            + ("Gol-patlaması bandına yakın." if (p6.get("compatibility_percent") or 0) >= 60 else "Klasik +6 senaryosu değil.")
        )

    lines.append("")
    lines.append("6) Birleşik karar")
    # synthesize
    hp, dp, ap = implied(q.get("h")), implied(q.get("d")), implied(q.get("a"))
    if hp or dp or ap:
        book_fav = max(
            [("ev", hp or 0), ("beraberlik", dp or 0), ("deplasman", ap or 0)],
            key=lambda x: x[1],
        )[0]
        if not hp:
            book_fav = book_fav  # MS 1 yoksa ima çarpık kalır
    else:
        book_fav = lider
    o25_book = implied(q.get("o25"))
    pahali_ust = bool(o25_book and o25_book * 100 - o25 >= 8)
    ucuz_ust = bool(o25_book and o25 - o25_book * 100 >= 8)
    model_fav = None
    if lh and lh.get("dixon_coles"):
        model_fav = max(
            [("ev", lh["dixon_coles"].get("ms1") or 0), ("beraberlik", lh["dixon_coles"].get("msx") or 0), ("deplasman", lh["dixon_coles"].get("ms2") or 0)],
            key=lambda x: x[1],
        )[0]
    para_fav = None
    if matched_bw:
        best = (-1, None)
        for key, lab in [("h", "ev"), ("d", "beraberlik"), ("a", "deplasman")]:
            pct = ((matched_bw.get("markets") or {}).get(key) or {}).get("money_pct") or -1
            if pct > best[0]:
                best = (pct, lab)
        para_fav = best[1]

    ayni = [lider]
    if model_fav:
        ayni.append(model_fav)
    if para_fav:
        ayni.append(para_fav)
    taraf_oy = Counter(ayni).most_common(1)[0]
    if not q.get("h"):
        lines.append("MS 1 oranı girilmediği için piyasa favorisi satırı eksik kalır; ev zaten kısa favori.")
    lines.append(
        f"Kalıp tarafı: {lider} (%{lp:.0f}). "
        + (f"Model tarafı: {model_fav}. " if model_fav else "")
        + (f"Betfair para tarafı: {para_fav}. " if para_fav else "Betfair teyidi yok. ")
        + (f"Piyasa favorisi: {book_fav}." if q.get("h") else "Piyasa MS 1 kutusu boş.")
    )
    avg = s.get("avg_goals") or 0
    if avg >= 3.2 or o25 >= 70:
        lines.append(f"Gol karakteri yüksek: ortalama {avg or '-'}, 2.5 üst %{o25:.0f}, 3.5 üst %{o35:.0f}. Düşük skor beklentisi yok.")
    elif avg and avg <= 2.3 or o25 <= 45:
        lines.append(f"Gol karakteri düşük/orta: ortalama {avg or '-'}, 2.5 üst %{o25:.0f}.")
    if q.get("o25") and pahali_ust:
        lines.append(f"2.5 üst geçmişte %{o25:.0f} gelmiş, piyasa yaklaşık %{o25_book*100:.0f} istiyor. Üst pahalı.")
    elif q.get("o25") and ucuz_ust:
        lines.append(f"2.5 üst geçmişte %{o25:.0f}, piyasa %{o25_book*100:.0f}. Üstte hafif değer olabilir.")
    if q.get("o35") and o35 >= 60:
        lines.append(f"3.5 üst kalıpta %{o35:.0f}. Oran {q.get('o35')} açık; tempo yüksek ama n={n} küçük.")
    elif not q.get("o35"):
        lines.append("3,5 üst bültende yok; o hatta yorum yok.")
    if n < 30:
        lines.append("Havuz küçük. Tek seçeneğe yüklenme.")
    ranked = score_open_picks(q, s, lh, standing)
    acik = open_markets(q)
    lines.append("Açık iddaa: " + (", ".join(f"{nm} {od}" for _, nm, od in acik) or "yok") + ".")
    if ranked:
        top3 = "; ".join(
            f"{x['name']} EV {x.get('ev')}" + (f" ({x['stand_note']})" if x.get("stand_note") else "")
            for x in ranked[:3]
        )
        lines.append("Açık piyasa sıralaması: " + top3 + ".")
    tercih = tercih_from_open(ranked, n)
    if taraf_oy[1] >= 2 and taraf_oy[0] == "ev" and q.get("h"):
        tercih.insert(1, "Kalıp/model ev tarafını destekliyor; kupon yalnızca açık MS 1 ile birleşir.")
    elif taraf_oy[1] >= 2 and taraf_oy[0] == "deplasman" and q.get("a"):
        tercih.insert(1, "Kalıp/model deplasman tarafını destekliyor; kupon yalnızca açık MS 2 ile birleşir.")
    lines.append("Bu metin kanıt değil. Kalıp + tablo + model + açık iddaa sentezi.")
    lines.append("")
    lines.append("[[ATASU_TERCIH]]")
    lines.extend(tercih[:6])
    lines.append("[[/ATASU_TERCIH]]")
    return "\n".join(lines)

def brief_from_odds(q, tol=0.05, league="", limit=200, title=""):
    match_title = title or ""
    pool, matches, minimum, _ = match_rows(q, tol, league)
    s = stats(matches)
    n = s.get("sample_ft") or 0
    p6 = plus6_payload(q)
    ev_name, dep_name = _parse_teams(match_title)
    standing = None
    try:
        standing = _standing(ev_name or "", dep_name or "", league or "")
    except Exception as e:
        standing = {"ok": False, "note": "Puan durumu alınamadı: " + str(e)[:80]}
    lines = []
    title = f"{n} eşleşen sonuçlu maç"
    if n:
        evp = s.get("MS 1")
        o25 = s.get("2,5 Üst")
        kg = s.get("KG Var")
        avg = s.get("avg_goals")
        bits = [f"n={n}"]
        if evp is not None:
            bits.append(f"ev %{evp:.0f}")
        if o25 is not None:
            bits.append(f"2.5 üst %{o25:.0f}")
        if kg is not None:
            bits.append(f"KG %{kg:.0f}")
        if avg is not None:
            bits.append(f"ort {avg}")
        lines.append(" · ".join(bits) + ".")
        tops = s.get("top_scores") or []
        if tops:
            lines.append("Sık skor: " + ", ".join(t["score"] for t in tops[:3]) + ".")
    else:
        lines.append("Bu oran bandında sonuçlu geçmiş maç yok.")
    bw = betwatch_find(match_title, q=q)
    bw["signals"] = money_signals(s, bw.get("overlay"), q)
    lh = lh_style_engine(q, s, standing)
    yorum = compact_yorum(
        s, matches, title=match_title or title, league=league, q=q, bw=bw, p6=p6, lh=lh, standing=standing,
    )
    open_rank = score_open_picks(q, s, lh, standing)
    banko = None
    if open_rank:
        banko = banko_evaluate(open_rank[0], n, standing=standing, lh=lh, stats_obj=s)
        if banko and banko.get("need"):
            extra_b = "\n".join(banko_lines(banko))
            if "[[ATASU_TERCIH]]" in yorum:
                yorum = yorum.replace("[[ATASU_TERCIH]]", extra_b + "\n\n[[ATASU_TERCIH]]", 1)
            else:
                yorum = yorum + "\n" + extra_b
    coach = None
    if coach_compose:
        try:
            coach = coach_compose({
                "standing": standing, "lh": lh, "stats": s,
                "sample": n, "matched": len(matches), "yorum": yorum,
            }, standing)
        except Exception as e:
            coach = {"ok": False, "note": str(e)[:80]}
    if banko and banko.get("karar") == "OYNA":
        try:
            led = ROOT / "data" / "ledger.json"
            rows = json.loads(led.read_text(encoding="utf-8")) if led.exists() else []
            pk = (banko.get("pick") or {})
            rows.append({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "title": match_title,
                "pick": pk.get("name") or "",
                "odds": pk.get("odds"),
                "karar": "OYNA",
                "label": banko.get("label"),
                "settled": None,
                "auto": True,
            })
            led.parent.mkdir(parents=True, exist_ok=True)
            led.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
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
        "lh_model": lh,
        "standing": standing,
        "coach": coach,
        "banko": banko,
        "open_markets": [{"key": k, "name": n, "odds": o} for k, n, o in open_markets(q)],
        "open_picks": open_rank,
        "version": "5.5.0",
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


class StandingReq(BaseModel):
    title: str = ""
    home: str = ""
    away: str = ""
    league: str = ""


@app.post("/api/standing")
def standing_api(req: StandingReq):
    home, away = req.home.strip(), req.away.strip()
    if not home or not away:
        home2, away2 = _parse_teams(req.title)
        home = home or (home2 or "")
        away = away or (away2 or "")
    if not home and not away:
        raise HTTPException(400, "Maç adı veya takım lazım.")
    try:
        pack = _standing(home, away, req.league or "")
    except Exception as e:
        raise HTTPException(502, "Puan durumu alınamadı: " + str(e)[:120])
    return pack


@app.get("/api/standing")
def standing_get(title: str = "", home: str = "", away: str = "", league: str = ""):
    return standing_api(StandingReq(title=title, home=home, away=away, league=league))


@app.post("/api/update")
def api_update():
    global HISTORY
    try:
        out = run_update(HISTORY)
        HISTORY = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else HISTORY
        out["history_n"] = len(HISTORY)
        out["version"] = "5.2.3"
        return out
    except Exception as e:
        raise HTTPException(502, "Güncelleme alınamadı: " + str(e)[:160])


@app.get("/api/update")
def api_update_status():
    st = _load_state()
    return {
        "version": "5.5.0",
        "history_n": len(HISTORY),
        "last": st.get("last"),
        "added_total": st.get("added"),
        "seasons": st.get("seasons"),
        "note": "Kod kendini yazmaz. POST /api/update canlı cache + history hasadı yapar.",
    }



from pydantic import BaseModel as _BM


class LiveWinReq(_BM):
    minute: int | None = None
    score: str | None = None
    home: str = ""
    away: str = ""
    o25: float | None = None


@app.post("/api/live-window")
def api_live_window(req: LiveWinReq):
    m = req.minute
    alert = None
    note = "Pre-match banko canlida iptal edilebilir."
    if m is None:
        return {"ok": False, "note": "dakika yok"}
    if 60 <= m <= 75:
        alert = "60-75 pencere"
        note = "Ikinci yari tempo. 0-0 / 1-0 ise late 2.5U veya 2.Y gol bak; favori kilitlendiyse cekil."
    elif m >= 80:
        alert = "gec"
        note = "Yeni pre-match banko acma."
    return {
        "ok": True,
        "minute": m,
        "score": req.score,
        "alert": alert,
        "note": note,
        "window_60_75": bool(m is not None and 60 <= m <= 75),
    }


LEDGER = ROOT / "data" / "ledger.json"


def _ledger_load():
    if LEDGER.exists():
        try:
            return json.loads(LEDGER.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


class LedgerReq(_BM):
    title: str = ""
    pick: str = ""
    odds: float | None = None
    karar: str = ""
    label: str = ""
    settled: str | None = None  # HIT / MISS


@app.post("/api/ledger")
def api_ledger(req: LedgerReq):
    rows = _ledger_load()
    rows.append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "title": req.title,
        "pick": req.pick,
        "odds": req.odds,
        "karar": req.karar,
        "label": req.label,
        "settled": req.settled,
    })
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    hits = sum(1 for r in rows if r.get("settled") == "HIT")
    miss = sum(1 for r in rows if r.get("settled") == "MISS")
    n = hits + miss
    return {"ok": True, "n": len(rows), "settled": n, "hit_pct": round(100 * hits / n, 1) if n else None}


@app.get("/api/ledger")
def api_ledger_get():
    rows = _ledger_load()
    hits = sum(1 for r in rows if r.get("settled") == "HIT")
    miss = sum(1 for r in rows if r.get("settled") == "MISS")
    n = hits + miss
    return {"ok": True, "rows": rows[-80:], "hit_pct": round(100 * hits / n, 1) if n else None, "settled": n}
