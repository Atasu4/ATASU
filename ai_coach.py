"""ATASU AI katmanı: sayısal motoru Türkçe analist metnine çevirir.

Varsayılan: kural tabanlı (anahtar yokken de çalışır).
XAI_API_KEY veya OPENAI_API_KEY varsa kısa LLM cümlesi eklenir.
"""
from __future__ import annotations

import json
import os
import urllib.request


def _p(x):
    return x if isinstance(x, (int, float)) else None


def compose(brief: dict | None = None, standing: dict | None = None) -> dict:
    brief = brief or {}
    st = standing or brief.get("standing") or {}
    lh = brief.get("lh") or {}
    s = brief.get("stats") or {}
    dc = (lh.get("dixon_coles") or {}) if isinstance(lh, dict) else {}
    mc = (lh.get("monte_carlo") or {}) if isinstance(lh, dict) else {}
    edges = (lh.get("edges") or []) if isinstance(lh, dict) else []
    an = st.get("analysis") or {}
    n = brief.get("sample") or brief.get("matched") or 0

    bullets = []
    o25 = s.get("2,5 Üst")
    kg = s.get("KG Var")
    sh = s.get("2.Y 1+ Gol")
    if o25 is not None:
        bullets.append(f"Benzer maçta 2.5 üst %{o25:.0f} (n={n}).")
    if kg is not None:
        bullets.append(f"KG %{kg:.0f}.")
    if sh is not None:
        bullets.append(f"2. yarı gol %{sh:.0f}.")
    if dc.get("p_o25") is not None:
        bullets.append(
            f"Dixon-Coles 2.5Ü %{dc['p_o25']:.0f} · KG %{dc.get('p_btts') or 0:.0f} · "
            f"MS {dc.get('ms1')}-{dc.get('msx')}-{dc.get('ms2')}."
        )
    if mc.get("p_o25") is not None:
        bullets.append(f"MC (tau) 2.5Ü %{mc['p_o25']:.0f} · 6+ %{mc.get('p_g6') or 0:.0f}.")
    if an.get("exp_total") is not None:
        bullets.append(f"Tablo λ toplam {an.get('exp_total')} · ev {an.get('exp_home')} / dep {an.get('exp_away')}.")
    if an.get("combo_o25") is not None:
        bullets.append(f"Form 2.5Ü %{an['combo_o25']:.0f}.")

    al = [e for e in edges if e.get("signal") == "AL"]
    pahali = [e for e in edges if e.get("signal") == "PAHALI"]
    if al:
        bullets.append("Model AL: " + ", ".join(f"{e.get('name')} EV {e.get('ev_percent')}%" for e in al[:3]) + ".")
    if pahali:
        bullets.append("Pahalı: " + ", ".join(e.get("name", "") for e in pahali[:3]) + ".")

    # isabet / ev özeti
    tercih = ""
    y = brief.get("yorum") or ""
    if "KARAR: OYNA" in y:
        tercih = "OYNA"
    elif "KARAR: GEÇ" in y:
        tercih = "GEÇ"
    else:
        tercih = "BELİRSİZ"

    if tercih == "OYNA":
        headline = "Motor tek iş öneriyor; isabet bandı veya EV eşiği geçildi."
        stance = "oyna"
    elif o25 and o25 >= 62 and n >= 30:
        headline = "Kalıp 2.5 üstü öne çekiyor; oran bandı kontrol et."
        stance = "izle"
    elif pahali and not al:
        headline = "Model iddaa fiyatını pahalı görüyor; kupon yok."
        stance = "gec"
    else:
        headline = "Sinyaller dağınık; tek iş yok."
        stance = "gec"

    text = headline + " " + " ".join(bullets[:6])
    llm = _maybe_llm(headline, bullets, tercih)
    if llm:
        text = llm.strip() + "\n\n" + text

    return {
        "ok": True,
        "engine": "atasu-coach",
        "llm": bool(llm),
        "stance": stance,
        "tercih_ref": tercih,
        "headline": headline,
        "bullets": bullets[:8],
        "text": text[:900],
        "note": "Sayısal katman DC/MC/kalıp. LLM yoksa kural metni.",
    }


def _maybe_llm(headline: str, bullets: list[str], tercih: str) -> str | None:
    key = os.environ.get("XAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    prompt = (
        "Kısa Türkçe bahis analisti ol. Abartma. 3 cümle. "
        f"Karar iskeleti: {tercih}. {headline} " + " ".join(bullets[:5])
    )
    url = "https://api.x.ai/v1/chat/completions" if os.environ.get("XAI_API_KEY") else "https://api.openai.com/v1/chat/completions"
    model = "grok-4" if os.environ.get("XAI_API_KEY") else "gpt-4o-mini"
    body = json.dumps({
        "model": model,
        "temperature": 0.2,
        "max_tokens": 180,
        "messages": [
            {"role": "system", "content": "Türkçe, sade, iddia etme. OYNA/GEÇ zaten hesaplandı."},
            {"role": "user", "content": prompt},
        ],
    }).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode())
        return (data.get("choices") or [{}])[0].get("message", {}).get("content")
    except Exception:
        return None
