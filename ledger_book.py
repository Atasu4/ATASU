"""Kasa + kupon defteri. Aynı maça ikinci bilet yok. Yarım Kelly tavanı."""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent
LEDGER = ROOT / "data" / "ledger.json"
BANK = ROOT / "data" / "bankroll.json"


def _load_rows() -> list:
    if LEDGER.exists():
        try:
            rows = json.loads(LEDGER.read_text(encoding="utf-8"))
            return rows if isinstance(rows, list) else []
        except Exception:
            return []
    alt = ROOT / "ledger.json"
    if alt.exists():
        try:
            rows = json.loads(alt.read_text(encoding="utf-8"))
            return rows if isinstance(rows, list) else []
        except Exception:
            return []
    return []


def _save_rows(rows: list):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def bankroll() -> dict:
    if BANK.exists():
        try:
            return json.loads(BANK.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"bank": 1000.0, "max_same_day": 3, "max_same_match": 1, "max_fraction": 0.04}


def set_bankroll(bank: float | None = None, **kw) -> dict:
    st = bankroll()
    if bank is not None:
        st["bank"] = float(bank)
    st.update({k: v for k, v in kw.items() if v is not None})
    BANK.parent.mkdir(parents=True, exist_ok=True)
    BANK.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    return st


def same_match_open(title: str, rows: list | None = None) -> int:
    t = (title or "").casefold().strip()
    n = 0
    for r in rows or _load_rows():
        if r.get("settled") in {"HIT", "MISS", "VOID"}:
            continue
        if (r.get("title") or "").casefold().strip() == t and r.get("karar") == "OYNA":
            n += 1
    return n


def today_open(rows: list | None = None) -> int:
    day = time.strftime("%Y-%m-%d")
    n = 0
    for r in rows or _load_rows():
        if str(r.get("ts") or "").startswith(day) and r.get("karar") == "OYNA" and not r.get("settled"):
            n += 1
    return n


def allow_ticket(title: str, half_kelly: float | None) -> dict:
    st = bankroll()
    rows = _load_rows()
    reasons = []
    if same_match_open(title, rows) >= int(st.get("max_same_match") or 1):
        reasons.append("aynı maçta açık kupon var")
    if today_open(rows) >= int(st.get("max_same_day") or 3):
        reasons.append("günlük kupon tavanı")
    cap = float(st.get("max_fraction") or 0.04)
    frac = float(half_kelly or 0)
    if frac > cap:
        reasons.append(f"½Kelly {frac:.3f} > tavan {cap:.3f}")
        frac = cap
    stake = round(float(st.get("bank") or 0) * frac, 2) if frac > 0 else 0
    return {
        "ok": not reasons,
        "reasons": reasons,
        "fraction": round(frac, 4),
        "stake": stake,
        "bank": st.get("bank"),
        "today": today_open(rows),
        "same_match": same_match_open(title, rows),
    }


def log_pick(title, pick, odds, karar, label=None, extra=None) -> dict:
    rows = _load_rows()
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "title": title,
        "pick": pick,
        "odds": odds,
        "karar": karar,
        "label": label,
        "settled": None,
        "auto": True,
    }
    if extra:
        row.update(extra)
    # aynı maç+pick tekrarını yazma
    key = (title or "", pick or "", karar or "")
    for prev in reversed(rows[-12:]):
        if (prev.get("title"), prev.get("pick"), prev.get("karar")) == key and not prev.get("settled"):
            return {"ok": True, "dedup": True, "n": len(rows)}
    rows.append(row)
    _save_rows(rows)
    return {"ok": True, "n": len(rows), "dedup": False}


def summary() -> dict:
    rows = _load_rows()
    settled = [r for r in rows if r.get("settled") in {"HIT", "MISS"}]
    hits = [r for r in settled if r["settled"] == "HIT"]
    by_pick = Counter((r.get("pick") or "?") for r in settled)
    hit_pick = Counter((r.get("pick") or "?") for r in hits)
    clv = []
    for r in rows:
        o, c = r.get("odds"), r.get("close")
        try:
            if o and c and float(o) > 1 and float(c) > 1:
                clv.append(round(float(o) / float(c) - 1, 4))
        except Exception:
            pass
    pnl = 0.0
    for r in settled:
        try:
            odd = float(r.get("odds") or 0)
            stake = float(r.get("stake") or 0)
        except Exception:
            continue
        if stake <= 0:
            continue
        pnl += stake * (odd - 1) if r["settled"] == "HIT" else -stake
    n = len(settled)
    return {
        "ok": True,
        "n": len(rows),
        "settled": n,
        "hit": len(hits),
        "miss": n - len(hits),
        "hit_pct": round(100 * len(hits) / n, 1) if n else None,
        "pnl": round(pnl, 2),
        "clv_avg": round(sum(clv) / len(clv) * 100, 2) if clv else None,
        "by_pick": {k: {"n": by_pick[k], "hit": hit_pick.get(k, 0)} for k in by_pick},
        "bank": bankroll(),
        "rows": rows[-80:],
    }
