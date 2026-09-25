"""Hakem / derbi / deplasman / haber / hava — sahte sayı uydurmaz."""
from __future__ import annotations

import os
import json
from urllib.request import Request, urlopen

import names

CITIES = {
    "galatasaray": "istanbul", "fenerbahce": "istanbul", "besiktas": "istanbul",
    "basaksehir": "istanbul", "kasimpasa": "istanbul", "eyupspor": "istanbul",
    "trabzonspor": "trabzon", "samsunspor": "samsun", "rizespor": "rize",
    "konyaspor": "konya", "sivasspor": "sivas", "kayserispor": "kayseri",
    "alanyaspor": "alanya", "antalyaspor": "antalya", "goztepe": "izmir",
    "gaziantep": "gaziantep", "hatayspor": "hatay",
    "manchester united": "manchester", "manchester city": "manchester",
    "liverpool": "liverpool", "everton": "liverpool",
    "arsenal": "london", "chelsea": "london", "tottenham": "london",
    "west ham": "london", "fulham": "london", "brentford": "london",
    "crystal palace": "london",
    "real madrid": "madrid", "atletico madrid": "madrid", "getafe": "madrid",
    "barcelona": "barcelona", "espanyol": "barcelona",
    "inter": "milan", "milan": "milan",
    "roma": "rome", "lazio": "rome",
    "bayern munich": "munich", "borussia dortmund": "dortmund",
    "paris saint germain": "paris",
}

DERBIES = {
    frozenset({"galatasaray", "fenerbahce"}),
    frozenset({"galatasaray", "besiktas"}),
    frozenset({"fenerbahce", "besiktas"}),
    frozenset({"manchester united", "manchester city"}),
    frozenset({"liverpool", "everton"}),
    frozenset({"arsenal", "tottenham"}),
    frozenset({"inter", "milan"}),
    frozenset({"roma", "lazio"}),
    frozenset({"real madrid", "barcelona"}),
    frozenset({"real madrid", "atletico madrid"}),
    frozenset({"barcelona", "espanyol"}),
}


def _city(team: str) -> str | None:
    c = names.canon(team)
    if c in CITIES:
        return CITIES[c]
    for k, v in CITIES.items():
        if names.same(team, k, 0.84):
            return v
    return None


def travel(home: str, away: str) -> dict:
    hc, ac = _city(home), _city(away)
    if not hc or not ac:
        return {"ok": False, "note": "şehir haritasında yok"}
    same = hc == ac
    return {
        "ok": True,
        "home_city": hc,
        "away_city": ac,
        "same_city": same,
        "label": "şehir derbisi / kısa yol" if same else f"{ac} → {hc}",
    }


def derby(home: str, away: str) -> bool:
    pair = frozenset({names.canon(home), names.canon(away)})
    if pair in DERBIES:
        return True
    for d in DERBIES:
        a, b = list(d)
        if names.same(home, a) and names.same(away, b):
            return True
        if names.same(home, b) and names.same(away, a):
            return True
    return False


def weather(city: str | None) -> dict:
    key = os.environ.get("OPENWEATHER_KEY") or os.environ.get("OPENWEATHER_API_KEY")
    if not key or not city:
        return {"ok": False, "note": "hava anahtarı yok"}
    try:
        url = (
            "https://api.openweathermap.org/data/2.5/weather?q="
            + city + "&appid=" + key + "&units=metric"
        )
        req = Request(url, headers={"User-Agent": "ATASU/5.7"})
        with urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
        main = (data.get("weather") or [{}])[0]
        wind = (data.get("wind") or {}).get("speed")
        temp = (data.get("main") or {}).get("temp")
        desc = main.get("description") or ""
        note = None
        if wind and float(wind) >= 9:
            note = "sert rüzgar — orta/uzun şut ve duran top sapar"
        if "rain" in desc or "storm" in desc:
            note = "ıslak zemin — tempo ve kontrol düşer"
        return {
            "ok": True,
            "city": city,
            "temp": temp,
            "wind": wind,
            "desc": desc,
            "note": note,
        }
    except Exception as e:
        return {"ok": False, "note": str(e)[:80]}


def referee_from_opta(home_opta: dict | None, away_opta: dict | None) -> dict:
    """Hakem adı yoksa kart/faul profilinden zayıf prior."""
    hop, aop = home_opta or {}, away_opta or {}
    cards = (hop.get("yellow") or 0) + (aop.get("yellow") or 0)
    fouls = (hop.get("fouls_pg") or 0) + (aop.get("fouls_pg") or 0)
    if not cards and not fouls:
        return {"ok": False, "note": "hakem feed yok"}
    return {
        "ok": True,
        "src": "takım kart/faul proxy",
        "yellow_sum": cards,
        "fouls_pg": round(fouls, 2) if fouls else None,
        "note": "hakem adı yok; yalnızca takım disiplin profili",
    }


def build(home: str, away: str, standing: dict | None = None, news: dict | None = None) -> dict:
    an = (standing or {}).get("analysis") or {}
    tr = travel(home, away)
    der = derby(home, away)
    ref = referee_from_opta(an.get("home_opta"), an.get("away_opta"))
    w = weather(tr.get("home_city"))
    flags = []
    if der:
        flags.append("derbi")
    if tr.get("same_city"):
        flags.append("aynı şehir")
    elif tr.get("ok"):
        flags.append("deplasman yol")
    if news and news.get("ok"):
        for it in news.get("items") or []:
            if it.get("tag") == "eksik":
                flags.append("kadro şüphesi")
                break
    if w.get("ok") and w.get("note"):
        flags.append("hava etkisi")
    return {
        "ok": True,
        "travel": tr,
        "derby": der,
        "referee": ref,
        "weather": w,
        "news": news or {"ok": False},
        "flags": flags,
    }
