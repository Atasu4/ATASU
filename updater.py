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
            "hg": hg,
            "ag": ag,
            "hh": None,
            "ha": None,
        }
        k = _key(row)
        if k in seen:
            continue
        history.append(row)
        seen.add(k)
        added += 1
    return history, added


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
    if total:
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
