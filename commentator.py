"""Tek ses: kapı listesi değil, stüdyo yorumcusu.

Sayılar içeride erir. Dışarıda maç nasıl biter, tek iş nedir, ne iptal eder.
"""
from __future__ import annotations

from mackolik_standing import score_open_picks, tercih_from_open, open_markets
from banko import evaluate as banko_evaluate
import ledger_book


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
    tercih_lines = tercih_from_open(ranked, n) if ranked else ["Açık iddaa satırı yok."]
    top = ranked[0] if ranked else None
    banko = banko_evaluate(top, n, standing=standing, lh=lh, stats_obj=stats_obj) if top else None

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

    # tek fikir
    karar = "GEC"
    pick = top
    why = []
    if top:
        odd = _f(top.get("odds"))
        blend = _f(top.get("blend_percent"))
        evp = _f(top.get("ev"))
        key = top.get("key")
        band = bool(odd and 1.30 <= odd <= 2.20)
        sample_ok = n >= 25
        blend_ok = bool(blend and blend >= 63)
        ev_ok = evp is None or evp >= 0
        if band and sample_ok and blend_ok and ev_ok:
            karar = "OYNA"
            why.append("fiyat, örnek ve birleşik okuma aynı yöne bakıyor")
        elif band and (blend_ok or (n >= 18 and ev_ok)):
            karar = "IZLE"
            why.append("yön var ama örnek veya kenar tam oturmadı")
        else:
            karar = "GEC"
            if not band:
                why.append("oran kupon bandının dışında")
            elif not sample_ok:
                why.append("benzer maç sayısı ince")
            else:
                why.append("birleşik okuma eşiğin altında")
    else:
        why.append("açık piyasadan iş çıkmadı")

    if banko and banko.get("label") == "BANKO-YAKIN" and karar != "OYNA":
        karar = "IZLE"
        why.append("kapılar neredeyse kilit ama yorumcu yine tek iş ister")
    if live and live.get("cancel"):
        karar = "IPTAL"
        why.append(live.get("idea") or "canlı tempo fikri bozdu")
    elif live and live.get("karar") == "IZLE" and karar == "OYNA":
        karar = "IZLE"
        why.append("60-75 pencere: beklet")

    ticket = ledger_book.allow_ticket(title or names, None)
    if karar == "OYNA" and not ticket.get("ok"):
        karar = "IZLE"
        why.extend(ticket.get("reasons") or [])

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
    if open_row and top:
        op = open_row.get(top.get("key"))
        cl = top.get("odds")
        try:
            if op and cl and float(op) > 1:
                d = round(float(cl) - float(op), 3)
                if d <= -0.08:
                    how.append(f"{top.get('name')} açılış {op} → {cl}, para bu tarafa yürümüş.")
                elif d >= 0.10:
                    how.append(f"{top.get('name')} açılış {op} → {cl}, piyasa soğumuş; kenar şüpheli.")
        except Exception:
            pass

    # 3. tek cümle karar
    if pick and karar == "OYNA":
        punch = (
            f"Tek iş: {pick.get('name')} {pick.get('odds')}. "
            + ("; ".join(why) + ".")
        )
    elif pick and karar == "IZLE":
        punch = (
            f"Yön {pick.get('name')} {pick.get('odds')} ama kupon yok. "
            + ("; ".join(why) + ".")
        )
    elif karar == "IPTAL":
        punch = "Canlı masa pre-match fikri kesti. " + (live.get("idea") or "")
    else:
        punch = "Bu maçta kupon yok. " + ("; ".join(why) + ".")

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
