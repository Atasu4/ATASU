"""İY/MS X/1 ÷ 1/1 filtresi — 1-0 biten maç referans bandı."""
from __future__ import annotations

from typing import Any, Dict, Optional

DEFAULT_REF = [
    (4.34, 5.27), (8.08, 9.63), (7.43, 10.10), (5.97, 7.62), (7.50, 9.98),
    (6.84, 9.41), (3.93, 5.54), (7.42, 10.60), (3.98, 5.73), (3.77, 5.76),
    (5.43, 8.43), (3.11, 4.84), (3.13, 5.19), (3.34, 5.53), (2.76, 4.49),
    (3.38, 5.67), (3.04, 5.22), (3.75, 6.49), (2.44, 4.53), (2.21, 4.13),
    (2.13, 4.21),
]
DEFAULT_REF2 = [
    (35.00, 35.00), (31.50, 31.50), (29.50, 29.00),
    (33.00, 32.50), (24.95, 25.50), (28.00, 25.50),
]
CELL_KEYS = ("ht11", "ht1x", "ht12", "htx1", "htxx", "htx2", "ht21", "ht2x", "ht22")
LABELS = ("1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2")


def _f(v):
    if v is None or v == "" or v == "-":
        return None
    try:
        x = float(str(v).replace(",", ".").strip())
        return x if x > 1 else None
    except (TypeError, ValueError):
        return None


def cells_from_odds(q: dict | None) -> Optional[Dict[str, float]]:
    q = q or {}
    a = _f(q.get("ht11") or q.get("1/1"))
    b = _f(q.get("htx1") or q.get("X/1"))
    if a is None or b is None:
        return None
    out = {"1/1": a, "X/1": b}
    mapping = {
        "1/X": ("ht1x", "1/X"),
        "1/2": ("ht12", "1/2"),
        "X/X": ("htxx", "X/X"),
        "X/2": ("htx2", "X/2"),
        "2/1": ("ht21", "2/1"),
        "2/X": ("ht2x", "2/X"),
        "2/2": ("ht22", "2/2"),
    }
    for lab, keys in mapping.items():
        for k in keys:
            v = _f(q.get(k))
            if v:
                out[lab] = v
                break
    return out


def evaluate(cells: dict | None) -> Optional[Dict[str, Any]]:
    if not cells:
        return None
    a = _f(cells.get("1/1"))
    b = _f(cells.get("X/1"))
    if not a or not b:
        return None
    ratios = [rb / ra for ra, rb in DEFAULT_REF]
    rt = b / a
    ref_min, ref_max = min(ratios), max(ratios)
    ref_avg = sum(ratios) / len(ratios)
    closest_idx = min(range(len(ratios)), key=lambda i: abs(ratios[i] - rt))
    closest_diff = abs(ratios[closest_idx] - rt)

    tag, tag_label = "good", "Referans aralığında"
    if rt < ref_min or rt > ref_max:
        margin = (ref_max - ref_min) * 0.15
        if ref_min - margin <= rt <= ref_max + margin:
            tag, tag_label = "mid", "Aralığa yakın"
        else:
            tag, tag_label = "bad", "Aralık dışı"

    c12, c21 = _f(cells.get("1/2")), _f(cells.get("2/1"))
    tag2 = tag2_label = None
    d12 = None
    if c12 and c21:
        d12 = abs(c12 - c21)
        diffs = [abs(x - y) for x, y in DEFAULT_REF2]
        r2min, r2max = min(diffs), max(diffs)
        if r2min <= d12 <= r2max:
            tag2, tag2_label = "good", "Referans aralığında"
        else:
            tag2, tag2_label = "bad", "Referans aralığında değil"

    if tag == "good":
        verdict, sub, banner = "1-0 İHTİMALİ GÜÇLÜ", "X/1 ÷ 1/1 referans bandının içinde.", "good"
    elif tag == "mid":
        verdict, sub, banner = "1-0 İHTİMALİ ORTA", "X/1 ÷ 1/1 banda yakın, tam içinde değil.", "mid"
    else:
        verdict, sub, banner = "1-0 İHTİMALİ ZAYIF", "X/1 ÷ 1/1 referans bandının dışında.", "bad"
    if tag2 == "good" and tag != "bad":
        banner = "good"
        sub += " 1/2≈2/1 yakınlığı destekliyor."
    if tag2 == "bad" and tag == "good":
        banner = "mid"
        sub += " 1/2 ile 2/1 farkı referanstan büyük."

    return {
        "ok": True,
        "one_one": a,
        "x_one": b,
        "ratio": round(rt, 3),
        "ref_min": round(ref_min, 3),
        "ref_avg": round(ref_avg, 3),
        "ref_max": round(ref_max, 3),
        "closest": closest_idx + 1,
        "closest_ratio": round(ratios[closest_idx], 3),
        "closest_diff": round(closest_diff, 3),
        "tag": tag,
        "tag_label": tag_label,
        "one_two": c12,
        "two_one": c21,
        "diff_12_21": None if d12 is None else round(d12, 2),
        "tag2": tag2,
        "tag2_label": tag2_label,
        "verdict": verdict,
        "sub": sub,
        "banner": banner,
        "cells": {k: _f(cells.get(k)) for k in LABELS},
    }


def evaluate_odds(q: dict | None) -> Optional[Dict[str, Any]]:
    return evaluate(cells_from_odds(q))


def lines(pack: dict | None) -> list[str]:
    if not pack:
        return []
    out = [
        f"İY/MS X/1÷1/1 {pack['ratio']} · ref {pack['ref_min']}-{pack['ref_max']} · {pack['verdict']}",
        f"1/1 {pack['one_one']} · X/1 {pack['x_one']} · {pack['tag_label']}",
    ]
    if pack.get("one_two") and pack.get("two_one"):
        out.append(
            f"1/2 {pack['one_two']} · 2/1 {pack['two_one']} · fark {pack.get('diff_12_21')} · {pack.get('tag2_label') or ''}"
        )
    out.append(pack.get("sub") or "")
    return [x for x in out if x]
