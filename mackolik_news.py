"""Maçkolik takım haberleri — başlık + kısa gövde + etki etiketi."""
from __future__ import annotations

import re
import time
from html import unescape
from urllib.request import Request, urlopen

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9",
}
_CACHE: dict[str, tuple[float, object]] = {}
TTL = 20 * 60
TAGS = [
    ("eksik", re.compile(r"sakat|cezal[ıi]|kadro d[ıi][sş][ıi]|oynamayacak|yoksun|ameliyat", re.I)),
    ("kadro", re.compile(r"ilk 11|kadrosu|kamp kadro|davet", re.I)),
    ("hoca", re.compile(r"teknik direkt[öo]r|istifa|görevden", re.I)),
    ("motiv", re.compile(r"dünya kupas[ıi]|final|derbi|kriz", re.I)),
]


def _cg(k):
    hit = _CACHE.get(k)
    if not hit:
        return None
    ts, val = hit
    if time.time() - ts > TTL:
        _CACHE.pop(k, None)
        return None
    return val


def _cs(k, v):
    _CACHE[k] = (time.time(), v)
    return v


def _fetch(url, limit=400000):
    r = Request(url, headers=UA)
    with urlopen(r, timeout=12) as f:
        raw = f.read(limit)
        enc = f.headers.get_content_charset() or "utf-8"
    return raw.decode(enc, errors="replace")


def _strip(html: str) -> str:
    html = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    html = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", html)
    html = re.sub(r"(?is)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", unescape(html)).strip()


def _tag(text: str):
    for name, rx in TAGS:
        if rx.search(text or ""):
            return name
    return None


def team_headlines(team_id: int, slug: str = "x", limit: int = 5) -> list[dict]:
    key = f"head:{team_id}"
    hit = _cg(key)
    if hit is not None:
        return hit
    try:
        html = _fetch(f"https://arsiv.mackolik.com/Takim/{int(team_id)}/{slug or 'x'}")
    except Exception:
        return _cs(key, [])
    seen, out = set(), []
    for m in re.finditer(r"Haber/(\d+)/([^\"'\s]+)", html):
        hid, sl = m.group(1), m.group(2)
        if hid in seen:
            continue
        seen.add(hid)
        out.append({
            "id": int(hid),
            "title": sl.replace("-", " "),
            "url": f"https://arsiv.mackolik.com/Haber/{hid}/{sl}",
        })
        if len(out) >= limit:
            break
    return _cs(key, out)


def article_snip(item: dict) -> dict:
    key = f"art:{item.get('id')}"
    hit = _cg(key)
    if hit is not None:
        return hit
    try:
        html = _fetch(item["url"], limit=220000)
    except Exception:
        item = dict(item); item.update({"body": "", "tag": None})
        return _cs(key, item)
    tm = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    item = dict(item)
    if tm:
        item["title"] = _strip(tm.group(1))[:140]
    lead = ""
    for rx in (r"<h2[^>]*>(.*?)</h2>", r"<p>(.*?)</p>"):
        m = re.search(rx, html, re.I | re.S)
        if m:
            lead = _strip(m.group(1))
            if len(lead) > 40:
                break
    for cut in ("Çerez", "Zorunlu Çerez"):
        i = lead.find(cut)
        if i > 60:
            lead = lead[:i]
    item["body"] = lead[:240]
    item["tag"] = _tag((item.get("title") or "") + " " + lead)
    return _cs(key, item)


def collect(home: str, away: str, standing: dict | None = None, max_items: int = 4) -> dict:
    st = standing or {}
    pairs = []
    for side, hk, rk in (("home", "home_hit", "home_row"), ("away", "away_hit", "away_row")):
        hit, row = st.get(hk) or {}, st.get(rk) or {}
        tid = hit.get("id") or row.get("team_id")
        slug = ""
        um = re.search(r"/Takim/\d+/([^/\s]+)", hit.get("url") or "")
        if um:
            slug = um.group(1)
        name = hit.get("name") or row.get("name") or (home if side == "home" else away)
        if tid:
            pairs.append((side, int(tid), slug, name))
    items = []
    for side, tid, slug, name in pairs:
        for h in team_headlines(tid, slug):
            art = article_snip(h)
            art["side"], art["team"] = side, name
            items.append(art)

    def score(it):
        t = ((it.get("title") or "") + " " + (it.get("body") or "")).casefold()
        sc = 0
        for q in (home, away):
            if q and q.casefold() in t:
                sc += 3
        if it.get("tag") == "eksik":
            sc += 4
        elif it.get("tag"):
            sc += 2
        return sc

    items.sort(key=score, reverse=True)
    picked = [x for x in items if score(x) > 0][:max_items] or items[:2]
    lines = []
    for it in picked:
        bit = it.get("title") or ""
        if it.get("tag"):
            bit = f"[{it['tag']}] {bit}"
        if it.get("team"):
            bit = f"{it['team']} — {bit}"
        lines.append(bit[:200])
    return {
        "ok": bool(picked),
        "source": "arsiv.mackolik.com/Haber",
        "n": len(picked),
        "items": picked,
        "lines": lines,
        "text": " ".join(lines[:3]),
    }


def preview_sentence(pack: dict | None) -> str:
    if not pack or not pack.get("lines"):
        return ""
    return "Haber: " + pack["lines"][0][:180] + "."
