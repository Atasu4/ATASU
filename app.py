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
if not HISTORY_FILE.exists() and (ROOT / "history.json").exists():
    HISTORY_FILE = ROOT / "history.json"
HISTORY = []
HISTORY_WARNING = None
try:
    if HISTORY_FILE.exists():
        HISTORY = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        if not isinstance(HISTORY, list):
            HISTORY = (HISTORY.get("matches") or HISTORY.get("history") or []) if isinstance(HISTORY, dict) else []
            if not isinstance(HISTORY, list):
                HISTORY = []
                HISTORY_WARNING = "history.json liste değil."
    else:
        HISTORY_WARNING = "data/history.json yok. Motorlar boş havuzla açıldı."
except Exception as e:
    HISTORY = []
    HISTORY_WARNING = "history okunamadı: " + str(e)[:80]
if not HISTORY_WARNING and not HISTORY:
    HISTORY_WARNING = "history.json boş. POST /api/update veya football-data hasadı çalıştır."

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
import filters
from banko import evaluate as banko_evaluate, lines as banko_lines
from version import VERSION
import commentator
import ledger_book
import live_desk
import context_layer
import xg_layer
try:
    from mackolik_news import collect as news_collect
except Exception:
    news_collect = None
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
        pack = xg_layer.enrich(pack, home or "", away or "", league or "")
    except Exception:
        pass
    news = None
    try:
        if news_collect:
            news = news_collect(home or "", away or "", pack)
            pack["news"] = news
    except Exception as e:
        pack["news"] = {"ok": False, "note": str(e)[:80]}
        news = pack["news"]
    try:
        pack["context"] = context_layer.build(home or "", away or "", standing=pack, news=news)
    except Exception as e:
        pack["context"] = {"ok": False, "note": str(e)[:80]}
    try:
        pack["pipeline"] = build_pipeline(
            home or "", away or "", standing=pack, extra=extra, league=league or "", news=news
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


app = FastAPI(title="ATASU Intelligence", version=VERSION)
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
    if an.get("npxg_home") and an.get("npxg_away"):
        w = 1.5 if an.get("npxg_src") == "opta" else 1.15
        cands_h.append((float(an["npxg_home"]), w))
        cands_a.append((float(an["npxg_away"]), w))
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
    for p in filters.match_profiles(q):
        hit.append({
            "id": p["id"],
            "selection": p["selection"],
            "hit_percent": p["hit_percent"],
            "sample": p["sample"],
            "wins": p["wins"],
            "why": p["why"],
            "checks": p["checks"],
            "match": True,
            "ref": p.get("ref_match"),
        })
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


@app.get("/indir")
def indir_zip():
    candidates = [
        ROOT / "ATASU.zip",
        Path("/workspace/artifacts/ATASU_5.7.0.zip"),
    ]
    p = next((c for c in candidates if c.exists()), None)
    if p is None:
        raise HTTPException(404, "Zip yok")
    return FileResponse(
        p,
        media_type="application/zip",
        filename=f"ATASU_{VERSION}.zip",
        content_disposition_type="attachment",
    )


@app.get("/api/meta")
def meta():
    return {
        "history_rows": len(HISTORY),
        "completed_rows": sum(score(x.get("ft")) is not None for x in HISTORY),
        "markets": MARKETS,
        "version": VERSION,
        "warning": HISTORY_WARNING,
        "rule": "Yorumcu tek iş konuşur. Kapılar içeride erir. Ledger kalibre eder.",
        "ledger": (ROOT / "data" / "ledger.json").exists(),
        "voice": "commentator",
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
        r"\[(\d+),'((?:\\'|[^'])*)',\d+,'((?:\\'|[^'])*)','?\d+'?,\d+,'(\d+:\d+)','(\d{2}\.\d{2}\.\d{4})'(?:,(.*?))?\](?=,\[|\]|\})",
        raw,
    ):
        mac_id, home, away, time, date_s, rest = m.groups()
        rest = rest or ""
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

        league = ""
        for p in parts:
            s = (p or "").strip()
            if not s or s.isdigit() or re.match(r"^\d+[.,]\d+$", s):
                continue
            if re.fullmatch(r"[A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜ0-9\-]{1,7}", s):
                league = s
                break
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


def _kick_sort_key(row: dict):
    d = str(row.get("date") or "")
    t = str(row.get("time") or row.get("kickoff") or "")
    dm = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", d)
    if dm:
        iso = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
    else:
        iso = d
    hm = re.search(r"(\d{1,2}):(\d{2})", t)
    clock = f"{int(hm.group(1)):02d}:{hm.group(2)}" if hm else "99:99"
    return (iso, clock, row.get("home") or "")


def _sort_bulletin(rows: list) -> list:
    return sorted(rows or [], key=_kick_sort_key)


def _bulletin_raw():
    last_err = None
    for week in (1, 0, 2):
        url = (
            "https://arsiv.mackolik.com/AjaxHandlers/ProgramDataHandler.ashx"
            f"?type=6&sortValue=DATE&week={week}&day=-1&sort=-1&sortDir=1&groupId=-1&np=0&sport=1"
        )
        try:
            raw = _fetch(url, limit=4000000)
            if raw and re.search(r"\[\d+,'", raw):
                return raw
        except Exception as e:
            last_err = e
            continue
    raise HTTPException(502, "Bülten alınamadı: " + str(last_err or "boş cevap")[:120])


@app.get("/api/bulletin")
def bulletin(date: str = ""):
    """Iddaa program listesi — resmi API değil."""
    raw = _bulletin_raw()
    rows = _parse_program_rows(raw)
    seen, uniq = set(), []
    for r in rows:
        k = r.get("mac_id")
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    rows = uniq
    want = ""
    filtered = rows
    if date.strip():
        ds = date.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", ds):
            y, mo, d = ds.split("-")
            want = f"{d}.{mo}.{y}"
        else:
            want = ds
        filtered = [r for r in rows if r["date"] == want]
        if not filtered:
            filtered = rows
            want = (want + " yok · hafta") if want else "hafta"
    filtered = _sort_bulletin(filtered)
    return {
        "ok": True,
        "source": "Mackolik ProgramDataHandler",
        "count": len(filtered),
        "date": want or "hafta",
        "sort": "saat",
        "matches": filtered[:500],
        "note": "Saat sırası. Resmi API değil. Bugün boşsa haftalık liste döner.",
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
    with urlopen(r, timeout=25) as f:
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
        return {
            "ok": True, "url": url, "title": title, "home": home, "away": away,
            "text": text[:120000], "chars": len(text), "source": source, "mac_id": mac_id,
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
        "version": VERSION,
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
    p6 = plus6_payload(q)
    ev_name, dep_name = _parse_teams(req.title or "")
    standing = None
    try:
        standing = _standing(ev_name or "", dep_name or "", req.league or "")
    except Exception:
        standing = None
    lh = lh_style_engine(q, s, standing)
    yorum = compact_yorum(
        s, matches, title=req.title or "", league=req.league or "", q=q, p6=p6, lh=lh, standing=standing,
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
    pack = commentator.compose(
        standing=standing, lh=lh, stats_obj=s, q=q or {}, title=title, n=s.get("sample_ft") or 0,
        p6=p6, news=(standing or {}).get("news"), context=(standing or {}).get("context"),
    )
    return commentator.wrap_yorum(pack)


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
    lh = lh_style_engine(q, s, standing)
    voice = commentator.compose(
        standing=standing, lh=lh, stats_obj=s, q=q, title=match_title or title,
        n=n, p6=p6, news=(standing or {}).get("news"),
        context=(standing or {}).get("context"),
        open_row={k: q.get("open_" + k) for k in ("h", "d", "a", "o25", "u25", "btts")},
    )
    yorum = commentator.wrap_yorum(voice)
    open_rank = score_open_picks(q, s, lh, standing)
    banko = voice.get("banko")
    coach = {
        "ok": True,
        "engine": "atasu-commentator-5.7",
        "text": voice.get("script"),
        "stance": voice.get("stance"),
        "headline": voice.get("headline"),
    }
    if voice.get("karar") == "OYNA" and voice.get("pick"):
        pk = voice["pick"]
        ticket = ledger_book.allow_ticket(match_title, None)
        if ticket.get("ok"):
            ledger_book.log_pick(
                match_title, pk.get("name"), pk.get("odds"), "OYNA",
                label=voice.get("karar"), extra={"blend": pk.get("blend"), "ev": pk.get("ev")},
            )
    return {
        "title": title,
        "text": voice.get("headline") or " ".join(lines),
        "sample": n,
        "stats": s,
        "plus6": p6,
        "matched": len(matches),
        "minimum_match_count": minimum,
        "pool_size": len(pool),
        "matches": matches[:limit],
        "yorum": yorum,
        "commentator": voice,
        "lh_model": lh,
        "standing": standing,
        "coach": coach,
        "banko": banko,
        "open_markets": [{"key": k, "name": n, "odds": o} for k, n, o in open_markets(q)],
        "open_picks": open_rank,
        "version": VERSION,
        "sources": {
            "standing": bool((standing or {}).get("ok")),
            "news": bool(((standing or {}).get("news") or {}).get("ok")),
            "xg": ((standing or {}).get("analysis") or {}).get("npxg_src"),
            "history": n,
        },
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
        out["version"] = VERSION
        return out
    except Exception as e:
        raise HTTPException(502, "Güncelleme alınamadı: " + str(e)[:160])


@app.get("/api/update")
def api_update_status():
    st = _load_state()
    return {
        "version": VERSION,
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
    pick_key: str | None = None
    pre_karar: str = ""


@app.post("/api/live-window")
def api_live_window(req: LiveWinReq):
    pack = live_desk.read(req.minute, req.score, pick_key=req.pick_key, pre_karar=req.pre_karar)
    pack["version"] = VERSION
    return pack


class LedgerReq(_BM):
    title: str = ""
    pick: str = ""
    odds: float | None = None
    karar: str = ""
    label: str = ""
    settled: str | None = None
    bank: float | None = None


@app.post("/api/ledger")
def api_ledger(req: LedgerReq):
    if req.bank is not None:
        ledger_book.set_bankroll(req.bank)
    if req.title or req.pick:
        ledger_book.log_pick(req.title, req.pick, req.odds, req.karar or "OYNA", req.label)
    return ledger_book.summary()


@app.get("/api/ledger")
def api_ledger_get():
    return ledger_book.summary()


class BankReq(_BM):
    bank: float | None = None
    max_same_day: int | None = None
    max_fraction: float | None = None


@app.post("/api/bankroll")
def api_bankroll(req: BankReq):
    return ledger_book.set_bankroll(req.bank, max_same_day=req.max_same_day, max_fraction=req.max_fraction)


@app.get("/api/bankroll")
def api_bankroll_get():
    s = ledger_book.summary()
    s["version"] = VERSION
    return s


@app.get("/api/desk")
def api_desk(tolerance: float = 0.08, bankroll: float = 1000, limit: int = 16):
    """Günlük masa: bülteni tara, yorumcu tek cümleyle dizer."""
    raw = api_oran_scan_bulletin(tolerance=tolerance, bankroll=bankroll, limit=limit)
    ranked = []
    for m in raw.get("matches") or []:
        q = {}
        for k in ("h", "d", "a", "u25", "o25", "btts"):
            if m.get(k):
                q[k] = m[k]
        if not q:
            extra = {x.get("key"): x.get("close") for x in (m.get("markets") or []) if x.get("key")}
            q.update({k: v for k, v in extra.items() if v})
        s_obj = {"sample_ft": m.get("sample") or 0}
        for x in m.get("markets") or []:
            if x.get("name") and x.get("hist") is not None:
                s_obj[x["name"]] = x["hist"]
        dc = {}
        for x in m.get("markets") or []:
            if x.get("key") == "h":
                dc["ms1"] = x.get("model")
            elif x.get("key") == "a":
                dc["ms2"] = x.get("model")
            elif x.get("key") == "d":
                dc["msx"] = x.get("model")
            elif x.get("key") == "o25":
                dc["p_o25"] = x.get("model")
            elif x.get("key") == "btts":
                dc["p_btts"] = x.get("model")
        voice = commentator.compose(
            stats_obj=s_obj,
            q=q,
            title=m.get("title") or f"{m.get('home') or ''} - {m.get('away') or ''}",
            n=m.get("sample") or 0,
            lh={"dixon_coles": dc} if dc else {},
            open_row={x.get("key"): x.get("open") for x in (m.get("markets") or []) if x.get("key")},
        )
        m["voice"] = commentator.blurb(voice)
        m["karar"] = voice.get("karar")
        m["script"] = voice.get("headline")
        m["scoreline"] = voice.get("scoreline")
        m["pick"] = voice.get("pick")
        ranked.append(m)
    order = {"OYNA": 0, "BIRIM": 1, "IZLE": 2, "GEC": 3, "IPTAL": 4}
    ranked.sort(key=lambda x: (order.get(x.get("karar") or "GEC", 9), -((x.get("best") or {}).get("ev") or -9)))
    raw["matches"] = ranked
    raw["desk"] = True
    raw["version"] = VERSION
    return raw


class OranScanReq(_BM):
    matches: list[dict] = []
    tolerance: float = 0.08
    bankroll: float = 1000.0
    limit: int = 40


def _odds_from_row(m: dict) -> dict:
    q = {}
    for k in MARKETS:
        v = _odd(m.get(k))
        if v:
            q[k] = v
    extra = m.get("odds") if isinstance(m.get("odds"), dict) else {}
    for k, v in extra.items():
        vv = _odd(v)
        if vv and (k in MARKETS or k in ("iy05", "nofirst", "o45")):
            q[k] = vv
    return q


def _open_from_row(m: dict, key: str):
    op = m.get("open") if isinstance(m.get("open"), dict) else {}
    return _odd(op.get(key)) or _odd(m.get("open_" + key))


def scan_one_oran(m: dict, tol: float, bankroll: float) -> dict:
    q = _odds_from_row(m)
    title = m.get("title") or f"{m.get('home') or ''} - {m.get('away') or ''}".strip(" -")
    league = m.get("league") or ""
    if len(q) < 2:
        return {
            "ok": False,
            "title": title,
            "home": m.get("home"),
            "away": m.get("away"),
            "kickoff": m.get("time"),
            "league": league,
            "note": "en az 2 oran yok",
            "markets": [],
        }
    _pool, matches, _minimum, fallback = match_rows(q, tol, league)
    s = stats(matches)
    n = s.get("sample_ft") or 0
    try:
        lh = lh_style_engine(q, s, None)
    except Exception:
        lh = {}
    ranked = score_open_picks(q, s, lh, None)
    banko = banko_evaluate(ranked[0], n, standing=None, lh=lh, stats_obj=s) if ranked else None
    rows = []
    for p in ranked:
        odd = p.get("odds")
        blend = p.get("blend_percent")
        p01 = (blend / 100.0) if isinstance(blend, (int, float)) else None
        kf = kelly_fraction(p01, odd) if p01 is not None else None
        half = round(kf / 2, 4) if kf else 0.0
        open_o = _open_from_row(m, p.get("key"))
        close_o = odd
        drift = None
        if open_o and close_o:
            drift = round(close_o - open_o, 3)
        rows.append({
            "key": p.get("key"),
            "name": p.get("name"),
            "open": open_o,
            "close": close_o,
            "drift": drift,
            "hist": p.get("hist_percent"),
            "model": p.get("model_percent"),
            "blend": blend,
            "n": n,
            "wilson_lo": p.get("wilson_lo"),
            "ev": p.get("ev"),
            "kelly_half": half,
            "stake": round(half * bankroll, 2) if half else 0.0,
        })
    return {
        "ok": True,
        "title": title,
        "home": m.get("home"),
        "away": m.get("away"),
        "kickoff": m.get("time") or m.get("kickoff"),
        "league": league,
        "mac_id": m.get("mac_id"),
        "sample": n,
        "fallback": fallback,
        "banko": banko,
        "best": rows[0] if rows else None,
        "markets": rows,
        "voice": None,
    }


@app.post("/api/oran-scan")
def api_oran_scan(req: OranScanReq):
    rows = req.matches[: max(1, min(int(req.limit or 40), 80))]
    out = [scan_one_oran(m, req.tolerance, req.bankroll) for m in rows]
    out.sort(key=lambda x: ((x.get("best") or {}).get("ev") or -9), reverse=True)
    return {
        "ok": True,
        "version": VERSION,
        "history_n": len(HISTORY),
        "n": len(out),
        "bankroll": req.bankroll,
        "tolerance": req.tolerance,
        "matches": out,
    }


@app.get("/api/oran-scan")
def api_oran_scan_bulletin(tolerance: float = 0.08, bankroll: float = 1000, limit: int = 24):
    """Bülteni çek, açık MS/2.5 olan maçları tara. Standing yok — hızlı tarama."""
    try:
        pack = bulletin("")
    except Exception as e:
        raise HTTPException(502, "Bülten: " + str(e)[:120])
    rows = []
    for m in pack.get("matches") or []:
        if _odd(m.get("h")) and _odd(m.get("d")) and _odd(m.get("a")):
            rows.append(m)
    rows = _sort_bulletin(rows)[:limit]
    return api_oran_scan(OranScanReq(matches=rows, tolerance=tolerance, bankroll=bankroll, limit=limit))


@app.get("/api/filter-scan")
def api_filter_scan(date: str = ""):
    """Tüm bülteni referans şablonlara vur. History taramaz."""
    pack = bulletin(date)
    hits = []
    scanned = 0
    for m in pack.get("matches") or []:
        q = {}
        for k in ("h", "d", "a", "u25", "o25", "btts", "nobtts"):
            v = _odd(m.get(k))
            if v:
                q[k] = v
        if len(q) < 2:
            continue
        scanned += 1
        profs = filters.match_profiles(q)
        if not profs:
            continue
        hits.append({
            "home": m.get("home"),
            "away": m.get("away"),
            "title": f"{m.get('home') or ''} - {m.get('away') or ''}".strip(" -"),
            "time": m.get("time"),
            "date": m.get("date"),
            "league": m.get("league"),
            "mac_id": m.get("mac_id"),
            "odds": q,
            "profiles": [{"id": p["id"], "name": p["name"], "selection": p["selection"],
                          "key": p.get("key"), "why": p.get("why")} for p in profs],
        })
    hits.sort(key=lambda x: (x.get("date") or "", x.get("time") or "99:99"))
    return {
        "ok": True,
        "source": pack.get("date"),
        "bulletin": pack.get("count"),
        "scanned": scanned,
        "n": len(hits),
        "matches": hits,
        "filters": [p["id"] for p in filters.PROFILES],
    }

