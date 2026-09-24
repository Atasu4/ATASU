"""Banko yaklasim skoru — kesinlik degil, katman mutabakati."""
from __future__ import annotations

from mackolik_standing import wilson_interval, HIT_KEYS, MIN_ODD, MAX_ODD, MIN_BLEND, MIN_WILSON_LO

# Bagimsiz kapilar. Hepsi evet olursa "banko-yakin"; 1 hayir = GEÇ.
GATES = [
    "oran_bandi",      # 1.30-1.70 kisa-orta (2.20 ustu banko degil)
    "ornek",           # n >= 40
    "wilson",          # alt >= 55
    "kalip",           # hist >= 65
    "model",           # DC >= 62
    "birlesik",        # blend >= 66
    "ev_pozitif",      # EV > 0
    "taraf_uyum",      # tablo λ / form ayni yonde
    "piyasa_oncelik",  # MS1 / 2.5U / KG
]


def _f(x):
    try:
        return float(x) if x is not None else None
    except Exception:
        return None


def evaluate(pick: dict, n_hist: int, standing=None, lh=None, stats_obj=None) -> dict:
    standing = standing or {}
    an = standing.get("analysis") or {}
    dc = ((lh or {}).get("dixon_coles") or {})
    key = pick.get("key")
    odd = _f(pick.get("odds"))
    hist = _f(pick.get("hist_percent"))
    model = _f(pick.get("model_percent"))
    blend = _f(pick.get("blend_percent"))
    ev = _f(pick.get("ev"))
    w = wilson_interval(hist, n_hist) if hist is not None else None
    wlo = (w or {}).get("lo")

    checks = {}
    checks["oran_bandi"] = bool(odd and 1.30 <= odd <= 1.70)
    checks["ornek"] = int(n_hist or 0) >= 40
    checks["wilson"] = bool(wlo is not None and wlo >= 55)
    checks["kalip"] = bool(hist is not None and hist >= 65)
    checks["model"] = bool(model is not None and model >= 62)
    checks["birlesik"] = bool(blend is not None and blend >= 66)
    checks["ev_pozitif"] = bool(ev is not None and ev > 0)
    checks["piyasa_oncelik"] = key in HIT_KEYS

    taraf = True
    if key == "o25":
        combo = an.get("combo_o25")
        lam = an.get("exp_total")
        if combo is not None and combo < 58:
            taraf = False
        if lam is not None and lam < 2.45:
            taraf = False
        if an.get("npxg_total") is not None and an["npxg_total"] < 2.40:
            taraf = False
    elif key == "u25":
        combo = an.get("combo_o25")
        lam = an.get("exp_total")
        if combo is not None and combo > 48:
            taraf = False
        if lam is not None and lam > 2.55:
            taraf = False
        if an.get("npxg_total") is not None and an["npxg_total"] > 2.60:
            taraf = False
    elif key == "h":
        eh, ea = an.get("exp_home"), an.get("exp_away")
        if eh is not None and ea is not None and eh < ea + 0.15:
            taraf = False
        nph, npa = an.get("npxg_home"), an.get("npxg_away")
        if nph is not None and npa is not None and nph < npa + 0.12:
            taraf = False
    elif key == "a":
        eh, ea = an.get("exp_home"), an.get("exp_away")
        if eh is not None and ea is not None and ea < eh + 0.15:
            taraf = False
        nph, npa = an.get("npxg_home"), an.get("npxg_away")
        if nph is not None and npa is not None and npa < nph + 0.12:
            taraf = False
    elif key == "btts":
        ck = an.get("combo_kg")
        if ck is not None and ck < 55:
            taraf = False
        nph, npa = an.get("npxg_home"), an.get("npxg_away")
        if nph is not None and npa is not None and (nph < 0.95 or npa < 0.90):
            taraf = False
    checks["taraf_uyum"] = taraf

    yes = sum(1 for v in checks.values() if v)
    total = len(checks)
    missing = [k for k, v in checks.items() if not v]
    if yes == total:
        label = "BANKO-YAKIN"
        karar = "OYNA"
    elif yes >= total - 1 and odd and odd <= 1.55:
        label = "SIKI ADAY"
        karar = "IZLE"
    else:
        label = "UZAK"
        karar = "GEC"

    need = [
        "Gercek banko yok; bu skor sadece kapi sayisi.",
        "Eksik: " + (", ".join(missing) if missing else "yok") + ".",
        "Kalibrasyon icin ledger (isabet gunlugu) sart.",
        "Canli 60-75: pre-match banko bile tempo bozarsa iptal.",
    ]
    return {
        "ok": True,
        "label": label,
        "karar": karar,
        "gates_yes": yes,
        "gates_total": total,
        "checks": checks,
        "missing": missing,
        "wilson": w,
        "need": need,
        "pick": {"key": key, "name": pick.get("name"), "odds": odd},
    }


def lines(pack: dict) -> list[str]:
    if not pack:
        return []
    out = [
        f"Banko kapi {pack['gates_yes']}/{pack['gates_total']} · {pack['label']}",
    ]
    miss = pack.get("missing") or []
    if miss:
        out.append("Acik kapi: " + ", ".join(miss) + ".")
    else:
        out.append("Dokuz kapi kapali. Yine de tek is / yarim Kelly.")
    out.append(f"Etiket karar: {pack['karar']}")
    return out
