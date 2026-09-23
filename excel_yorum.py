#!/usr/bin/env python3
"""
ATASU / LH Bet Predict — Excel analog maç özetleyici + takım formu yorumu

Kullanım:
  python excel_yorum.py
  python excel_yorum.py --ornek

Fonksiyonlar uygulamaya import edilebilir:
  from excel_yorum import ozetle, yorumla
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Veri modelleri
# ---------------------------------------------------------------------------

@dataclass
class AnalogMac:
    tarih: str = ""
    lig: str = ""
    ev: str = ""
    dep: str = ""
    iy_ev: int | None = None
    iy_dep: int | None = None
    ms_ev: int | None = None
    ms_dep: int | None = None
    tutan: str = ""  # "7/10" gibi


@dataclass
class TakimFormu:
    ad: str
    son_maclar: list[str] = field(default_factory=list)  # "W","D","L"
    gol_atan: list[int] = field(default_factory=list)
    gol_yiyen: list[int] = field(default_factory=list)
    ev_mi: bool = True
    notlar: str = ""


@dataclass
class MacBaglami:
    ev: TakimFormu
    dep: TakimFormu
    lig: str = ""
    kaynak_link: str = ""
    ekstra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Özet istatistik
# ---------------------------------------------------------------------------

def _skor(a: int | None, b: int | None) -> str | None:
    if a is None or b is None:
        return None
    return f"{a}-{b}"


def _sonuc(ev: int, dep: int) -> str:
    if ev > dep:
        return "1"
    if ev < dep:
        return "2"
    return "X"


def ozetle(maclar: list[AnalogMac]) -> dict[str, Any]:
    n = len(maclar)
    if n == 0:
        return {"n": 0}

    ms_say = Counter()
    iy_say = Counter()
    ms_1x2 = Counter()
    iy_1x2 = Counter()
    ust25 = 0
    ust35 = 0
    kg_var = 0
    iy_gol_var = 0
    ev_ust = 0
    dep_ust = 0
    tutan_ok = 0
    tutan_toplam = 0
    ligler = Counter()
    ikinci_yari_gol = 0

    for m in maclar:
        if m.lig:
            ligler[m.lig] += 1
        ms = _skor(m.ms_ev, m.ms_dep)
        iy = _skor(m.iy_ev, m.iy_dep)
        if ms:
            ms_say[ms] += 1
            assert m.ms_ev is not None and m.ms_dep is not None
            ms_1x2[_sonuc(m.ms_ev, m.ms_dep)] += 1
            toplam = m.ms_ev + m.ms_dep
            if toplam >= 3:
                ust25 += 1
            if toplam >= 4:
                ust35 += 1
            if m.ms_ev > 0 and m.ms_dep > 0:
                kg_var += 1
            if m.ms_ev >= 2:
                ev_ust += 1
            if m.ms_dep >= 2:
                dep_ust += 1
        if iy:
            iy_say[iy] += 1
            assert m.iy_ev is not None and m.iy_dep is not None
            iy_1x2[_sonuc(m.iy_ev, m.iy_dep)] += 1
            if m.iy_ev + m.iy_dep > 0:
                iy_gol_var += 1
            if m.ms_ev is not None and m.ms_dep is not None:
                if (m.ms_ev + m.ms_dep) > (m.iy_ev + m.iy_dep):
                    ikinci_yari_gol += 1
        if "/" in (m.tutan or ""):
            try:
                a, b = m.tutan.replace(" ", "").split("/")
                tutan_ok += int(a)
                tutan_toplam += int(b)
            except ValueError:
                pass

    def pct(x: int, den: int | None = None) -> float:
        d = den if den is not None else n
        return round(100.0 * x / d, 1) if d else 0.0

    return {
        "n": n,
        "ms_en_sik": ms_say.most_common(5),
        "iy_en_sik": iy_say.most_common(5),
        "ms_1x2": dict(ms_1x2),
        "iy_1x2": dict(iy_1x2),
        "ust25_pct": pct(ust25),
        "ust35_pct": pct(ust35),
        "kg_pct": pct(kg_var),
        "iy_gol_pct": pct(iy_gol_var),
        "iy_gol_n": iy_gol_var,
        "ikinci_yari_gol_pct": pct(ikinci_yari_gol),
        "ev_2plus_pct": pct(ev_ust),
        "dep_2plus_pct": pct(dep_ust),
        "tutan_oran": f"{tutan_ok}/{tutan_toplam}" if tutan_toplam else None,
        "tutan_pct": pct(tutan_ok, tutan_toplam) if tutan_toplam else None,
        "ligler": ligler.most_common(6),
    }


def _form_ozet(t: TakimFormu) -> dict[str, Any]:
    n = len(t.son_maclar)
    w = t.son_maclar.count("W")
    d = t.son_maclar.count("D")
    l = t.son_maclar.count("L")
    gf = sum(t.gol_atan) if t.gol_atan else None
    ga = sum(t.gol_yiyen) if t.gol_yiyen else None
    ort_gf = round(gf / len(t.gol_atan), 2) if t.gol_atan else None
    ort_ga = round(ga / len(t.gol_yiyen), 2) if t.gol_yiyen else None
    return {
        "ad": t.ad,
        "n": n,
        "WDL": f"{w}-{d}-{l}",
        "ort_atan": ort_gf,
        "ort_yiyen": ort_ga,
        "ev_mi": t.ev_mi,
        "notlar": t.notlar,
    }


# ---------------------------------------------------------------------------
# Yorum metni
# ---------------------------------------------------------------------------

def _1x2_satir(c: dict[str, int], n: int) -> str:
    if not n:
        return "yetersiz örnek"
    p1 = 100.0 * c.get("1", 0) / n
    px = 100.0 * c.get("X", 0) / n
    p2 = 100.0 * c.get("2", 0) / n
    return f"1 %{p1:.0f} · X %{px:.0f} · 2 %{p2:.0f}"


def _skor_kisa(pairs: list[tuple[str, int]], n: int, limit: int = 3) -> str:
    if not pairs:
        return "-"
    return " ".join(f"{s} %{100 * k / n:.0f}" for s, k in pairs[:limit])


def yorumla(
    maclar: list[AnalogMac],
    baglam: MacBaglami | None = None,
    hedef: str = "",
) -> str:
    o = ozetle(maclar)
    n = o["n"]
    s: list[str] = []

    baslik = hedef.strip() or (
        f"{baglam.ev.ad}–{baglam.dep.ad}" if baglam else "analog özet"
    )
    s.append(baslik + (f" · {baglam.lig}" if baglam and baglam.lig else ""))

    if n == 0:
        s.append("havuz boş, yorum yok")
        return "\n".join(s)

    lig_txt = " ".join(f"{k}×{v}" for k, v in o["ligler"][:4]) if o["ligler"] else ""
    s.append(f"n={n}" + (f" · {lig_txt}" if lig_txt else "") + " · farklı lig=kalıp")
    s.append(f"ms {_1x2_satir(o['ms_1x2'], n)} · iy {_1x2_satir(o['iy_1x2'], n)}")
    s.append(f"ms sık {_skor_kisa(o['ms_en_sik'], n)} · iy sık {_skor_kisa(o['iy_en_sik'], n)}")
    s.append(
        f"2.5ü %{o['ust25_pct']:.0f} · 3.5ü %{o['ust35_pct']:.0f} · kg %{o['kg_pct']:.0f} · "
        f"iy gol %{o['iy_gol_pct']:.0f} · 2.y %{o['ikinci_yari_gol_pct']:.0f}"
    )
    extra = f"ev2+ %{o['ev_2plus_pct']:.0f} · dep2+ %{o['dep_2plus_pct']:.0f}"
    if o["tutan_oran"]:
        extra += f" · tutan {o['tutan_oran']} (%{o['tutan_pct']:.0f})"
    s.append(extra)

    if baglam is None:
        s.append("form yok")
    else:
        ev, dep = _form_ozet(baglam.ev), _form_ozet(baglam.dep)
        evg = f" {ev['ort_atan']}/{ev['ort_yiyen']}" if ev["ort_atan"] is not None else ""
        depg = f" {dep['ort_atan']}/{dep['ort_yiyen']}" if dep["ort_atan"] is not None else ""
        s.append(f"ev {ev['ad']} {ev['WDL']}{evg} · dep {dep['ad']} {dep['WDL']}{depg}")
        notlar = " · ".join(x for x in (baglam.ev.notlar, baglam.dep.notlar) if x)
        if notlar:
            s.append(notlar)

    egilim = []
    if o["ust25_pct"] >= 65:
        egilim.append("havuz golcü")
    elif o["ust25_pct"] <= 40:
        egilim.append("havuz düşük skor")
    else:
        egilim.append("orta gol")

    ms = o["ms_1x2"]
    lider = max(ms, key=ms.get) if ms else None
    if lider == "1" and ms.get("1", 0) / n >= 0.45:
        egilim.append("analog ev")
    elif lider == "2" and ms.get("2", 0) / n >= 0.45:
        egilim.append("analog dep")
    elif lider == "X" and ms.get("X", 0) / n >= 0.35:
        egilim.append("analog X")
    else:
        egilim.append("ms dağınık")

    if o["kg_pct"] >= 60:
        egilim.append("kg sık")
    elif o["kg_pct"] <= 35:
        egilim.append("tek kapı var")

    if baglam:
        ev_n = len(baglam.ev.son_maclar)
        dep_n = len(baglam.dep.son_maclar)
        ev_w = baglam.ev.son_maclar.count("W")
        dep_l = baglam.dep.son_maclar.count("L")
        if ev_n >= 3 and ev_w / ev_n >= 0.6 and lider == "1":
            egilim.append("ev form uyumlu")
        if dep_n >= 3 and dep_l / dep_n >= 0.5 and lider == "1":
            egilim.append("dep form ev destekler")
        ev_ort = _form_ozet(baglam.ev)["ort_atan"]
        dep_ort_y = _form_ozet(baglam.dep)["ort_yiyen"]
        if ev_ort and dep_ort_y and ev_ort >= 1.4 and dep_ort_y >= 1.3 and o["ust25_pct"] >= 55:
            egilim.append("form+havuz 2.5ü")
        if ev_ort is not None and ev_ort < 1.0 and o["ust25_pct"] >= 65:
            egilim.append("çelişki: ev az atıyor")

    uyari = "birebir 0 = kanıt değil"
    if o["tutan_pct"] is not None and o["tutan_pct"] >= 70:
        uyari += " · tutan yüksek, lige bak"
    elif o["tutan_pct"] is not None and o["tutan_pct"] < 55:
        uyari += " · tutan zayıf"
    s.append("okuma: " + " · ".join(egilim))
    s.append(uyari)
    return "\n".join(s)


# ---------------------------------------------------------------------------
# Ekrandaki tabloyu hızlı parse (kopyala-yapıştır)
# ---------------------------------------------------------------------------

def parse_tablo_satirlari(satirlar: list[str]) -> list[AnalogMac]:
    """
    Beklenen kaba format (ekrandaki gibi):
      2026-05-15 | DANI1 | B93 KOPENHAG - AALBORG BK | IY 1-1 | MS 1-1 | 7/10
    veya boşluklu serbest metin.
    """
    out: list[AnalogMac] = []
    for raw in satirlar:
        line = " ".join(raw.strip().split())
        if not line or line.upper().startswith("TARIH"):
            continue
        m = AnalogMac()
        parts = [p.strip() for p in line.replace("–", "-").split("|")]
        if len(parts) >= 5:
            m.tarih, m.lig = parts[0], parts[1]
            taraflar = parts[2].split(" - ")
            if len(taraflar) == 2:
                m.ev, m.dep = taraflar[0].strip(), taraflar[1].strip()
            iy = parts[3].replace("İY", "").replace("IY", "").strip()
            ms = parts[4].replace("MS", "").strip()
            if "-" in iy:
                a, b = iy.split("-", 1)
                try:
                    m.iy_ev, m.iy_dep = int(a), int(b)
                except ValueError:
                    pass
            if "-" in ms:
                a, b = ms.split("-", 1)
                try:
                    m.ms_ev, m.ms_dep = int(a), int(b)
                except ValueError:
                    pass
            if len(parts) >= 6:
                m.tutan = parts[5]
            out.append(m)
    return out


# Ekran görüntüsündeki örnek (kullanıcının Excel çıktısı)
EKRAN_ORNEK = [
    AnalogMac("2026-05-15", "DANI1", "B93 Kopenhag", "Aalborg BK", 1, 1, 1, 1, "7/10"),
    AnalogMac("2026-05-17", "POLEK", "Katowice", "Jagiellonia Bialystok", 1, 2, 1, 2, "10/12"),
    AnalogMac("2026-08-07", "KAFLK", "Cruz Azul", "Philadelphia Union", 1, 1, 0, 0, "8/12"),
    AnalogMac("2026-06-12", "AVUGA", "Adelaide Comets FC", "West Adelaide FC", 1, 3, 0, 0, "6/9"),
    AnalogMac("2026-05-16", "ALBO", "V Aschaffenburg", "Bayern Munih II", None, None, None, None, "6/9"),
]


def ornek_notts() -> str:
    """Notts County bağlamı + ekrandaki analoglar."""
    baglam = MacBaglami(
        ev=TakimFormu(
            ad="Notts County",
            son_maclar=["L", "L", "D", "D", "W"],
            gol_atan=[0, 0, 1, 1, 2],
            gol_yiyen=[2, 1, 1, 1, 1],
            ev_mi=True,
            notlar="L1 form zayıf · Trophy Grimsby 2-1",
        ),
        dep=TakimFormu(
            ad="Grimsby Town",
            son_maclar=["W", "W", "D", "W", "L"],
            gol_atan=[2, 2, 1, 2, 1],
            gol_yiyen=[0, 1, 1, 0, 2],
            ev_mi=False,
            notlar="lig formu Notts'tan canlı",
        ),
        lig="EFL Trophy / League One çevresi",
        kaynak_link="(Mackolik / bülten linki buraya)",
    )
    return yorumla(EKRAN_ORNEK, baglam, hedef="Notts County vs Grimsby Town")


if __name__ == "__main__":
    import sys

    if "--ornek" in sys.argv or len(sys.argv) == 1:
        print(ornek_notts())
    else:
        print("Kullanım: python excel_yorum.py --ornek")
        print("Kod içinden: yorumla(maclar, baglam)")
