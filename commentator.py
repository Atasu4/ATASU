"""Tek ses: kapı listesi değil, stüdyo yorumcusu.

Sayılar içeride erir. Dışarıda maç nasıl biter, tek iş nedir, ne iptal eder.
"""
from __future__ import annotations

from mackolik_standing import score_open_picks, tercih_from_open, open_markets
from banko import evaluate as banko_evaluate
import ledger_book
import filters


def _f(x):
    return x if isinstance(x, (int, float)) else None


def _ima(odd):
    try:
        odd = float(odd)
        return round(100 / odd, 1) if odd > 1 else None
    except Exception:
        return None


def _scoreline(dc, stats_obj, an):
    tops = (stats_obj or {}).get("top_scores") or []
    if tops:
        band = ", ".join(t.get("score") for t in tops[:3] if t.get("score"))
        if band:
            return band
    eh, ea = an.get("exp_home"), an.get("exp_away")
    if eh is None:
        eh = dc.get("lambda_home")
    if ea is None:
        ea = dc.get("lambda_away")
    if eh is None or ea is None:
        return None
    h = 1 if eh < 1.35 else 2 if eh < 2.15 else 3
    a = 0 if ea < 0.85 else 1 if ea < 1.45 else 2
    alt = f"{max(0, h-1)}-{a}" if h else f"0-{a}"
    return f"{h}-{a} / {alt}"


def _choose(ranked, q, n, dc):
    """Her maçta bir aday seç. Kısa 1.10'u ele, yoksa favori açık iş."""
    ranked = list(ranked or [])
    prefer = ("h", "o25", "btts", "u25", "a", "o35")

    def odd_of(x):
        return _f(x.get("odds")) if isinstance(x, dict) else None

    in_band = []
    for x in ranked:
        o = odd_of(x)
        if o and 1.22 <= o <= 2.45:
            in_band.append(x)
    pool = in_band or [x for x in ranked if odd_of(x) and odd_of(x) >= 1.22]
    if not pool and q:
        # ranked boşsa implied favori
        cand = []
        names = {"h": "MS 1", "a": "MS 2", "d": "MS X", "o25": "2,5 Üst", "u25": "2,5 Alt", "btts": "KG Var"}
        for k in prefer:
            o = _f(q.get(k))
            if o and o >= 1.22:
                cand.append({"key": k, "name": names.get(k, k), "odds": o, "blend_percent": dc.get({
                    "h": "ms1", "a": "ms2", "d": "msx", "o25": "p_o25", "btts": "p_btts",
                }.get(k)), "ev": None, "hist_percent": None, "model_percent": None})
        pool = cand
    if not pool:
        return None
    def rank_key(x):
        o = odd_of(x) or 99
        blend = _f(x.get("blend_percent")) or 0
        ev = _f(x.get("ev"))
        evs = ev if ev is not None else -0.2
        pref = 3 if x.get("key") in ("h", "o25", "btts") else 1
        band = 2 if 1.28 <= o <= 2.20 else 0
        return (pref + band, evs, blend)
    pool.sort(key=rank_key, reverse=True)
    return pool[0]


def _verdict(pick, n, dc):
    if not pick:
        return "GEC", ["açık iş yok"], 0
    odd = _f(pick.get("odds"))
    blend = _f(pick.get("blend_percent"))
    hist = _f(pick.get("hist_percent"))
    model = _f(pick.get("model_percent"))
    ev = _f(pick.get("ev"))
    why = []
    if odd and odd < 1.22:
        return "GEC", ["oran çok kısa, kenar yok"], 0
    if odd and odd > 2.60 and (blend or 0) < 48:
        return "GEC", ["uzun fiyat, okuma tutmuyor"], 0
    lean = False
    if blend is not None and blend >= 54:
        lean = True
        why.append(f"birleşik %{blend:.0f}")
    if hist is not None and hist >= 55:
        lean = True
        why.append(f"kalıp %{hist:.0f}")
    if model is not None and model >= 54:
        lean = True
        why.append(f"model %{model:.0f}")
    if ev is not None and ev >= -0.02:
        lean = True
        why.append(f"EV {ev}")
    if not lean and dc:
        key = pick.get("key")
        mp = {"h": "ms1", "a": "ms2", "d": "msx", "o25": "p_o25", "btts": "p_btts"}.get(key)
        if mp and _f(dc.get(mp)) and _f(dc.get(mp)) >= 50:
            lean = True
            why.append(f"Dixon-Coles %{dc.get(mp)}")
    if not why:
        why.append("piyasa favorisi açık iş")
        lean = bool(odd and 1.25 <= odd <= 2.10)
    strong = bool(
        odd and 1.28 <= odd <= 2.25
        and lean
        and (blend is None or blend >= 56 or (model or 0) >= 56 or (hist or 0) >= 58)
        and (ev is None or ev >= -0.05)
        and (n >= 8 or model is not None or blend is not None)
    )
    if strong:
        return "OYNA", why, None
    if lean and odd and 1.22 <= odd <= 2.45:
        return "OYNA", why + ["ince örnek, yine de bu iş"], None
    if odd and 1.25 <= odd <= 2.00:
        return "OYNA", why + ["favori açık iş"], None
    return "GEC", why or ["yön yok"], None


def compose(brief: dict | None = None, standing=None, lh=None, stats_obj=None,
            q=None, title="", n=0, p6=None, news=None, context=None,
            live=None, open_row=None) -> dict:
    brief = brief or {}
    standing = standing if standing is not None else brief.get("standing") or {}
    lh = lh if lh is not None else brief.get("lh") or brief.get("lh_model") or {}
    stats_obj = stats_obj if stats_obj is not None else brief.get("stats") or {}
    q = q or {}
    n = n or brief.get("sample") or brief.get("matched") or stats_obj.get("sample_ft") or 0
    an = (standing or {}).get("analysis") or {}
    dc = (lh or {}).get("dixon_coles") or {}
    hr = (standing or {}).get("home_row") or {}
    ar = (standing or {}).get("away_row") or {}
    ranked = score_open_picks(q, stats_obj, lh, standing) if q else (brief.get("open_picks") or [])
    pick = _choose(ranked, q, n, dc)
    prof = filters.annotate(q)
    st = None
    try:
        import strategy as _st
        st = _st.pick(q, title)
    except Exception:
        st = None
    if st and st.get("karar") == "OYNA" and st.get("key"):
        pick = {"key": st["key"], "name": st.get("name"), "odds": st.get("odds"),
                "blend_percent": None, "hist_percent": None, "model_percent": None}
        why_prof = [st.get("label") or st.get("strategy")]
    elif prof.get("hits"):
        want = {x.get("key") for x in prof["hits"] if x.get("key")}
        alt = next((x for x in (ranked or []) if x.get("key") in want), None)
        if not alt and q:
            names = {"a": "MS 2", "btts": "KG Var", "h": "MS 1", "o25": "2,5 Üst"}
            for h in prof["hits"]:
                k = h.get("key")
                if _f(q.get(k)):
                    alt = {"key": k, "name": names.get(k, k), "odds": q.get(k),
                           "blend_percent": None, "hist_percent": None, "model_percent": None}
                    break
        if alt:
            pick = alt
            why_prof = [x.get("name") for x in prof["hits"]]
        else:
            why_prof = []
    else:
        why_prof = []
    tercih_lines = tercih_from_open(ranked, n) if ranked else ["Açık iddaa satırı yok."]
    banko = banko_evaluate(pick, n, standing=standing, lh=lh, stats_obj=stats_obj) if pick else None

    ev = hr.get("name") or ""
    dep = ar.get("name") or ""
    head = title.split("|")[0].strip() if title else "Maç"
    names = f"{ev}–{dep}" if ev and dep else head

    o25 = _f(stats_obj.get("2,5 Üst"))
    kg = _f(stats_obj.get("KG Var"))
    ms1 = _f(stats_obj.get("MS 1"))
    ms2 = _f(stats_obj.get("MS 2"))
    sh = _f(stats_obj.get("2.Y 1+ Gol"))
    avg = stats_obj.get("avg_goals")

    karar, why, _unit = _verdict(pick, n, dc)
    if why_prof:
        why = why_prof + why
        if karar == "GEC":
            karar = "OYNA"
    if live and live.get("cancel"):
        karar = "IPTAL"
        why.append(live.get("idea") or "canlı tempo fikri bozdu")
    elif live and live.get("window_60_75") and karar == "OYNA":
        why.append("60-75: canlı tempo bozulursa bırak")

    ticket = ledger_book.allow_ticket(title or names, None)

    # 1. sahne
    scene = [names]
    if hr.get("pos") and ar.get("pos"):
        scene.append(
            f"ligde {hr['pos']}. ({hr.get('pts')}p) evde, {ar['pos']}. ({ar.get('pts')}p) dışarıda"
        )
    if context and context.get("derby"):
        scene.append("bu bir derbi — tempo istatistiği kadar gurur da konuşur")
    tr = (context or {}).get("travel") or {}
    if tr.get("same_city"):
        scene.append("aynı şehir, yol bahanesi yok")
    elif tr.get("ok"):
        scene.append(tr.get("label") or "deplasman yolu var")
    if an.get("exp_total") is not None:
        scene.append(f"tablo temposu {an.get('exp_home')}+{an.get('exp_away')} ≈ {an['exp_total']}")
    if an.get("npxg_total") is not None:
        scene.append(
            f"npxG {an.get('npxg_home')} / {an.get('npxg_away')} "
            f"(toplam {an['npxg_total']}, {an.get('npxg_src') or 'proxy'})"
        )
    if news and news.get("lines"):
        scene.append("masa notu: " + news["lines"][0])
    w = (context or {}).get("weather") or {}
    if w.get("ok") and w.get("note"):
        scene.append(w["note"])

    # 2. nasıl biter
    how = []
    if q.get("h") and q.get("a"):
        if q["a"] < q["h"]:
            how.append(
                f"Piyasa deplasmanı öne koyuyor (MS2 {q['a']}, ima %{_ima(q['a'])}; ev {q['h']})."
            )
        else:
            how.append(
                f"Piyasa evi favori yazıyor (MS1 {q['h']}, ima %{_ima(q['h'])}; dep {q['a']})."
            )
    if n:
        how.append(
            f"Aynı fiyat bandında {n} bitmiş maç: "
            f"MS {ms1}/{stats_obj.get('MS X')}/{ms2}, 2.5Ü %{o25}, KG %{kg}"
            + (f", 2. yarı gol %{sh}" if sh is not None else "")
            + (f", ortalama {avg}." if avg else ".")
        )
        if n < 30:
            how.append("Örnek 30'un altında; yüzdeye tapılmaz, yöne bakılır.")
    else:
        how.append("Bu fiyatın geçmişi yok; masa tablo ve modelle konuşuyor.")
    if dc.get("ms1") is not None:
        how.append(
            f"Dixon-Coles {dc.get('lambda_home')}–{dc.get('lambda_away')} → "
            f"MS {dc.get('ms1')}–{dc.get('msx')}–{dc.get('ms2')}, "
            f"2.5Ü %{dc.get('p_o25')}, KG %{dc.get('p_btts')}."
        )
    sl = _scoreline(dc, stats_obj, an)
    if sl:
        how.append(f"Skor bandı: {sl}.")

    # drift
    if open_row and pick:
        op = open_row.get(pick.get("key"))
        cl = pick.get("odds")
        try:
            if op and cl and float(op) > 1:
                d = round(float(cl) - float(op), 3)
                if d <= -0.08:
                    how.append(f"{pick.get('name')} açılış {op} → {cl}, fiyat bu tarafa yürümüş.")
                elif d >= 0.10:
                    how.append(f"{pick.get('name')} açılış {op} → {cl}, piyasa soğumuş.")
        except Exception:
            pass

    # 3. tek cümle karar
    if pick and karar == "OYNA":
        punch = f"Oyna: {pick.get('name')} {pick.get('odds')}. " + ("; ".join(why) + ".")
    elif pick and karar == "IZLE":
        punch = f"Yön {pick.get('name')} {pick.get('odds')}; netleşsin. " + ("; ".join(why) + ".")
    elif karar == "IPTAL":
        punch = "Canlı masa fikri kesti. " + (live.get("idea") or "")
    elif pick:
        punch = f"Geç. En yakın iş {pick.get('name')} {pick.get('odds')}. " + ("; ".join(why) + ".")
    else:
        punch = "Açık iddaa yok. " + ("; ".join(why) + ".")

    kill = "Fikir ölür: tempo tersine döner"
    if pick and pick.get("key") == "o25":
        kill = "Fikir ölür: ilk 30'da şut yok, 60-75 hâlâ 0-0/1-0 ve kanatlar durmuş."
    elif pick and pick.get("key") == "h":
        kill = "Fikir ölür: ev erken geride kalır veya npxG farkı deplasmana döner."
    elif pick and pick.get("key") == "a":
        kill = "Fikir ölür: ev erken öne geçer, deplasman yarı sahaya hapsolur."
    elif pick and pick.get("key") == "btts":
        kill = "Fikir ölür: bir taraf kalesini kilitler, ikinci kapı 60'ta hâlâ 0."
    if live and live.get("idea"):
        kill = live["idea"]

    cal = ledger_book.summary()
    cal_bit = ""
    if cal.get("settled"):
        cal_bit = (
            f" Defter: {cal['settled']} sonuç, isabet %{cal.get('hit_pct')}."
        )
        if cal.get("clv_avg") is not None:
            cal_bit += f" Ortalama CLV %{cal['clv_avg']}."

    p6bit = ""
    if p6 and p6.get("compatibility_percent") is not None:
        pc = p6["compatibility_percent"]
        if pc >= 70:
            p6bit = " +6 bandı bu temayı tutuyor."
        elif pc <= 35:
            p6bit = " +6 senaryosu değil; gol şöleni beklenmesin."

    script = (
        names + " — " + "; ".join(scene[1:] or ["masa kuruldu"]) + ". "
        + " ".join(how) + " "
        + punch + p6bit + " "
        + kill + cal_bit
    )
    script = " ".join(script.split())

    tercih_block = [
        f"KARAR: {karar}",
        punch,
        f"Skor bandı: {sl or '—'}",
        kill,
    ]
    if pick:
        tercih_block.append(
            f"İş {pick.get('name')} {pick.get('odds')}"
            + (f" · birleşik %{pick.get('blend_percent')}" if pick.get("blend_percent") is not None else "")
        )
    if why_prof:
        tercih_block.append("Şablon: " + ", ".join(why_prof))
    tercih_block.extend(tercih_lines[:3])

    return {
        "ok": True,
        "engine": "atasu-commentator-5.7",
        "stance": karar.lower(),
        "karar": karar,
        "headline": punch,
        "script": script[:1400],
        "scoreline": sl,
        "kill": kill,
        "pick": {
            "key": (pick or {}).get("key"),
            "name": (pick or {}).get("name"),
            "odds": (pick or {}).get("odds"),
            "blend": (pick or {}).get("blend_percent"),
            "ev": (pick or {}).get("ev"),
        } if pick else None,
        "tercih_lines": tercih_block,
        "banko": banko,
        "why": why,
        "profiles": prof,
        "text": script[:1400],
        "ticket": ticket,
    }


def wrap_yorum(pack: dict) -> str:
    lines = [pack.get("script") or pack.get("text") or ""]
    lines += ["", "[[ATASU_TERCIH]]"]
    lines.extend(pack.get("tercih_lines") or [])
    lines.append("[[/ATASU_TERCIH]]")
    return "\n".join(lines)


def blurb(pack: dict) -> str:
    karar = pack.get("karar") or "GEC"
    pick = pack.get("pick") or {}
    sl = pack.get("scoreline") or ""
    name = pick.get("name") or "iş yok"
    odd = pick.get("odds")
    bit = f"{karar} · {name}" + (f" {odd}" if odd else "")
    if sl:
        bit += f" · skor {sl}"
    return bit
