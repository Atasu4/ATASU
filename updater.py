"""ATASU otomatik güncelleme: cache temizle + biten maçları history.json'a yaz."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from mackolik_standing import TTL, _CACHE, fetch_standing

ROOT = Path(__file__).resolve().parent
HISTORY_FILE = ROOT / "data" / "history.json"
STATE_FILE = ROOT / "data" / "update_state.json"

# Sık kullanılan ligler — Tara sonrası season_id state'e eklenir
DEFAULT_SEASONS = [73482]  # Süper Lig güncel


def clear_live_cache() -> int:
    n = len(_CACHE)
    _CACHE.clear()
    return n


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"seasons": list(DEFAULT_SEASONS), "last": None, "added": 0}


def remember_season(season_id: int | None):
    if not season_id:
        return
    st = _load_state()
    ids = list(dict.fromkeys([int(season_id), *(st.get("seasons") or [])]))
    st["seasons"] = ids[:12]
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def _key(row: dict) -> str:
    return "|".join([
        str(row.get("date") or ""),
        str(row.get("home") or "").casefold(),
        str(row.get("away") or "").casefold(),
        str(row.get("ft") or ""),
    ])


def _odd(v):
    try:
        f = float(v)
        return f if f > 1 else None
    except Exception:
        return None


def _parse_ft(s: str):
    m = re.search(r"(\d+)\s*[-–]\s*(\d+)", str(s or ""))
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _norm_date(s: str) -> str:
    s = str(s or "").strip()
    # 20/09 -> 2026-09-20 (yıl yoksa güncel yıl)
    m = re.fullmatch(r"(\d{2})/(\d{2})", s)
    if m:
        y = datetime.now(timezone.utc).year
        return f"{y}-{m.group(2)}-{m.group(1)}"
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{2,4})", s)
    if m:
        y = int(m.group(3))
        if y < 100:
            y += 2000
        return f"{y}-{m.group(2)}-{m.group(1)}"
    return s


def harvest_season(season_id: int, history: list[dict]) -> tuple[list[dict], int]:
    pack = fetch_standing(int(season_id))
    if not pack:
        return history, 0
    names = pack.get("names") or {}
    seen = {_key(r) for r in history}
    added = 0
    for r in pack.get("results") or []:
        if str(r.get("status") or "").upper() not in {"MS", "FT", "BİTTİ", "BITTI"}:
            # standing.r zaten bitmiş maç; status MS
            if not r.get("ft"):
                continue
        hg, ag = _parse_ft(r.get("ft") or r.get("ft_raw") or "")
        if hg is None:
            continue
        home = names.get(r.get("home_id"))
        away = names.get(r.get("away_id"))
        if not home or not away:
            continue
        row = {
            "date": _norm_date(r.get("date")),
            "league": str(season_id),
            "home": str(home).upper(),
            "away": str(away).upper(),
            "ht": None,
            "ft": f"{hg} - {ag}",
            "h": _odd(r.get("h")),
            "d": _odd(r.get("d")),
            "a": _odd(r.get("a")),
            "u25": _odd(r.get("u25")),
            "o25": _odd(r.get("o25")),
            "u35": None,
            "o35": None,
            "btts": None,
            "nobtts": None,
            "g01": None,
            "g23": None,
            "g45": None,
            "g6": None,
            "iyu15": None,
            "iyo15": None,
            "iyh": _odd(r.get("iyh")),
            "iyd": _odd(r.get("iyd")),
            "iya": _odd(r.get("iya")),
            "hg": hg,
            "ag": ag,
            "hh": None,
            "ha": None,
            "res_o25": int(hg + ag >= 3),
            "res_o35": int(hg + ag >= 4),
            "res_btts": int(hg > 0 and ag > 0),
            "res_g6": int(hg + ag >= 6),
        }
        k = _key(row)
        if k in seen:
            continue
        history.append(row)
        seen.add(k)
        added += 1
    return history, added



def backfill_flags(history: list[dict]) -> int:
    n = 0
    for r in history:
        hg, ag = r.get("hg"), r.get("ag")
        if hg is None or ag is None:
            hg, ag = _parse_ft(r.get("ft") or "")
        if hg is None:
            continue
        r["hg"], r["ag"] = int(hg), int(ag)
        flags = {
            "res_o25": int(hg + ag >= 3),
            "res_o35": int(hg + ag >= 4),
            "res_btts": int(hg > 0 and ag > 0),
            "res_g6": int(hg + ag >= 6),
        }
        if any(r.get(k) != v for k, v in flags.items()):
            r.update(flags)
            n += 1
    return n


def harvest_football_data(history: list[dict]) -> int:
    """Buyuk lig kapanis oranlarini history havuzuna ekle."""
    try:
        from extra_feeds import load_league, LEAGUE_FILES, SEASON
    except Exception:
        return 0
    seen = {_key(r) for r in history}
    added = 0

    def fd_date(s):
        s = str(s or "").strip()
        return _norm_date(s)

    for code, name in LEAGUE_FILES.items():
        try:
            rows = load_league(code)
        except Exception:
            continue
        for r in rows:
            hg, ag = r.get("hg"), r.get("ag")
            if hg is None:
                continue
            row = {
                "date": fd_date(r.get("date")),
                "league": f"FD-{code}",
                "home": str(r.get("home") or "").upper(),
                "away": str(r.get("away") or "").upper(),
                "ht": (f"{r.get('hh')} - {r.get('ha')}" if r.get("hh") is not None and r.get("ha") is not None else None),
                "ft": f"{hg} - {ag}",
                "h": r.get("b365h"),
                "d": r.get("b365d"),
                "a": r.get("b365a"),
                "u25": r.get("b365u25"),
                "o25": r.get("b365o25"),
                "u35": None,
                "o35": None,
                "btts": None,
                "nobtts": None,
                "g01": None,
                "g23": None,
                "g45": None,
                "g6": None,
                "iyu15": None,
                "iyo15": None,
                "hg": hg,
                "ag": ag,
                "hh": None,
                "ha": None,
                "res_o25": int(hg + ag >= 3),
                "res_o35": int(hg + ag >= 4),
                "res_btts": int(hg > 0 and ag > 0),
                "res_g6": int(hg + ag >= 6),
                "src": "fd.co.uk",
                "fd_season": SEASON,
            }
            k = _key(row)
            if k in seen:
                continue
            history.append(row)
            seen.add(k)
            added += 1
    return added


def settle_ledger(history: list[dict]) -> dict:
    path = ROOT / "data" / "ledger.json"
    if not path.exists():
        return {"settled": 0, "hit": 0, "miss": 0}
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"settled": 0, "hit": 0, "miss": 0}

    def fold(s):
        return " ".join(str(s or "").casefold().split())

    idx = {}
    for r in history:
        idx[(fold(r.get("home")), fold(r.get("away")), str(r.get("date") or "")[:10])] = r
        idx[(fold(r.get("home")), fold(r.get("away")), "")] = r

    hit = miss = did = 0
    for row in rows:
        if row.get("settled") in {"HIT", "MISS"}:
            continue
        title = fold(row.get("title") or "")
        if " - " in title:
            home, away = [x.strip() for x in title.split(" - ", 1)]
        else:
            continue
        # latest matching teams
        cand = None
        for r in reversed(history):
            if fold(r.get("home")) == fold(home) and fold(r.get("away")) == fold(away) and r.get("ft"):
                cand = r
                break
        if not cand:
            continue
        hg, ag = cand.get("hg"), cand.get("ag")
        if hg is None:
            hg, ag = _parse_ft(cand.get("ft"))
        if hg is None:
            continue
        pick = str(row.get("pick") or "").casefold()
        won = None
        if "2,5 üst" in pick or "2.5 üst" in pick or pick.endswith("o25"):
            won = (hg + ag) >= 3
        elif "2,5 alt" in pick or "2.5 alt" in pick:
            won = (hg + ag) <= 2
        elif "kg var" in pick:
            won = hg > 0 and ag > 0
        elif "kg yok" in pick:
            won = not (hg > 0 and ag > 0)
        elif pick.startswith("ms 1") or pick == "h":
            won = hg > ag
        elif pick.startswith("ms 2") or pick == "a":
            won = ag > hg
        elif pick.startswith("ms x") or pick == "d":
            won = hg == ag
        if won is None:
            continue
        row["settled"] = "HIT" if won else "MISS"
        row["ft"] = cand.get("ft")
        did += 1
        if won:
            hit += 1
        else:
            miss += 1
    if did:
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return {"settled": did, "hit": hit, "miss": miss}


def run_update(history: list[dict], extra_seasons: list[int] | None = None) -> dict:
    cleared = clear_live_cache()
    st = _load_state()
    seasons = list(dict.fromkeys([*(extra_seasons or []), *(st.get("seasons") or DEFAULT_SEASONS)]))
    total = 0
    per = {}
    for sid in seasons:
        try:
            history, n = harvest_season(int(sid), history)
            per[str(sid)] = n
            total += n
        except Exception as e:
            per[str(sid)] = f"hata: {e}"
    try:
        fd_n = harvest_football_data(history)
        per["fd.csv"] = fd_n
        total += fd_n
    except Exception as e:
        per["fd.csv"] = f"hata: {e}"
    flags = backfill_flags(history)
    per["flags"] = flags
    led = settle_ledger(history)
    per["ledger"] = led
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    st["last"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    st["added"] = int(st.get("added") or 0) + total
    st["seasons"] = seasons[:12]
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "cache_cleared": cleared,
        "added": total,
        "per_season": per,
        "history_n": len(history),
        "last": st["last"],
        "ttl_sec": TTL,
        "note": "Kod sürümü değişmez. Canlı tablo cache silindi; biten maçlar history.json'a eklendi.",
    }
