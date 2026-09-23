#!/usr/bin/env python3
"""football-data.co.uk CSV -> ATASU_Benzer_Oran_Motoru.xlsx Arsiv.

Kullanım:
  python3 yukle_football_data.py
  python3 yukle_football_data.py --xlsx /path/ATASU_Benzer_Oran_Motoru.xlsx --dir /path/fd

CSV'de:
  B365H/D/A + B365>2.5  = açılışa yakın
  B365CH/CD/CA + B365C>2.5 = kapanış (C = closing)
Biz kapanışı Arsiv oran kolonuna yazarız (bot Kapanış modu).
"""
from __future__ import annotations

import argparse
import csv
import math
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

DIV_LIG = {
    "E0": "İngiltere - Premier Lig",
    "E1": "İngiltere - Championship",
    "SP1": "İspanya - La Liga",
    "SP2": "İspanya - Segunda",
    "D1": "Almanya - Bundesliga",
    "D2": "Almanya - 2. Bundesliga",
    "I1": "İtalya - Serie A",
    "I2": "İtalya - Serie B",
    "F1": "Fransa - Ligue 1",
    "F2": "Fransa - Ligue 2",
    "N1": "Hollanda - Eredivisie",
    "P1": "Portekiz - Liga Portugal",
    "T1": "Türkiye - Süper Lig",
    "B1": "Belçika - Pro League",
    "SC0": "İskoçya - Premiership",
    "G1": "Yunanistan - Super League",
}

YELLOW = PatternFill("solid", fgColor="FEF08A")
BLUE_FONT = Font(name="Arial", size=9, color="0000FF")
NORM = Font(name="Arial", size=9, color="0F172A")
THIN = Border(
    left=Side(style="thin", color="CBD5E1"),
    right=Side(style="thin", color="CBD5E1"),
    top=Side(style="thin", color="CBD5E1"),
    bottom=Side(style="thin", color="CBD5E1"),
)
CENTER = Alignment(horizontal="center", vertical="center")
LEFT = Alignment(horizontal="left", vertical="center")


def num(x):
    if x is None:
        return None
    s = str(x).strip()
    if s == "" or s.upper() in {"NA", "N/A", "#N/A", "-"}:
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def parse_date(s):
    s = (s or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def poisson_sf_ge3(lam: float) -> float:
    """P(K>=3) = 1 - P(0)-P(1)-P(2)."""
    if lam <= 0:
        return 0.0
    p0 = math.exp(-lam)
    p1 = p0 * lam
    p2 = p1 * lam / 2.0
    return max(0.0, min(1.0, 1.0 - p0 - p1 - p2))


def lambda_from_over25(p_over: float) -> float:
    """Binary search total expected goals from P(over 2.5)."""
    if p_over is None:
        return None
    p_over = min(0.92, max(0.08, p_over))
    lo, hi = 0.4, 5.5
    for _ in range(40):
        mid = (lo + hi) / 2
        if poisson_sf_ge3(mid) < p_over:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def split_lambda(ltot, h, d, a):
    """Split total lambda using 1X2 implied strength."""
    if ltot is None or not h or not d or not a:
        return None, None
    ph, pd, pa = 1 / h, 1 / d, 1 / a
    s = ph + pd + pa
    ph, pa = ph / s, pa / s
    # home share of goals ~ 0.35 + 0.30*(ph-pa normalized-ish)
    share = 0.50 + 0.35 * (ph - pa)
    share = min(0.78, max(0.22, share))
    return round(ltot * share, 3), round(ltot * (1 - share), 3)


def pick(row, *keys):
    for k in keys:
        if k in row and num(row[k]) is not None:
            return num(row[k])
    return None


def load_csv(path: Path):
    rows = []
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    reader = csv.DictReader(raw.splitlines())
    for r in reader:
        div = (r.get("Div") or "").strip()
        dt = parse_date(r.get("Date"))
        home = (r.get("HomeTeam") or "").strip()
        away = (r.get("AwayTeam") or "").strip()
        fth = num(r.get("FTHG"))
        fta = num(r.get("FTAG"))
        if not dt or not home or not away or fth is None or fta is None:
            continue
        # closing first, fallback opening
        ms1 = pick(r, "B365CH", "PSCH", "AvgCH", "B365H", "PSH", "AvgH")
        msx = pick(r, "B365CD", "PSCD", "AvgCD", "B365D", "PSD", "AvgD")
        ms2 = pick(r, "B365CA", "PSCA", "AvgCA", "B365A", "PSA", "AvgA")
        u25 = pick(r, "B365C>2.5", "PC>2.5", "AvgC>2.5", "B365>2.5", "P>2.5", "Avg>2.5")
        a25 = pick(r, "B365C<2.5", "PC<2.5", "AvgC<2.5", "B365<2.5", "P<2.5", "Avg<2.5")
        if not ms1 or not msx or not ms2:
            continue
        hth = num(r.get("HTHG"))
        hta = num(r.get("HTAG"))
        p_over = None
        if u25 and a25:
            po, pu = 1 / u25, 1 / a25
            p_over = po / (po + pu)
        elif u25:
            p_over = min(0.9, 1 / u25)
        ltot = lambda_from_over25(p_over) if p_over else None
        lev, ldep = split_lambda(ltot, ms1, msx, ms2)
        # BTTS yok — KG boş bırak
        rows.append(
            {
                "date": dt,
                "lig": DIV_LIG.get(div, div or "Bilinmeyen"),
                "ev": home,
                "dep": away,
                "ms1": ms1,
                "msx": msx,
                "ms2": ms2,
                "u25": u25,
                "a25": a25,
                "kgv": None,
                "kgy": None,
                "se": int(fth),
                "sd": int(fta),
                "iye": int(hth) if hth is not None else None,
                "iyd": int(hta) if hta is not None else None,
                "an": "Kapanış",
                "not": f"fd.co.uk {div} λ≈{ltot:.2f}" if ltot else f"fd.co.uk {div}",
                "lam_tot": ltot,
                "lam_ev": lev,
                "lam_dep": ldep,
            }
        )
    return rows


def write_arsiv(ws, rows, max_rows=500):
    # keep headers row 2; write from row 3; Motor reads 3..502
    start, cap = 3, max_rows
    # unmerge leftover note rows (keep title A1)
    for rng in list(ws.merged_cells.ranges):
        s = str(rng)
        if s.startswith("A1:"):
            continue
        ws.unmerge_cells(s)
    # clear old 3..502 and leftover sample notes area a bit
    for r in range(start, start + cap + 20):
        for c in range(1, 22):
            cell = ws.cell(r, c)
            if type(cell).__name__ == "MergedCell":
                continue
            cell.value = None
            cell.fill = PatternFill()
            cell.border = Border()

    extra_headers = {19: "λ tot", 20: "λ ev", 21: "λ dep"}
    for col, name in extra_headers.items():
        cell = ws.cell(2, col, name)
        cell.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1E293B")
        cell.alignment = CENTER
        ws.column_dimensions[cell.column_letter].width = 9

    for i, rec in enumerate(rows[:cap]):
        r = start + i
        vals = [
            i + 1,
            rec["date"],
            rec["lig"],
            rec["ev"],
            rec["dep"],
            rec["ms1"],
            rec["msx"],
            rec["ms2"],
            rec["u25"],
            rec["a25"],
            rec["kgv"],
            rec["kgy"],
            rec["se"],
            rec["sd"],
            rec["iye"],
            rec["iyd"],
            rec["an"],
            rec["not"],
            rec["lam_tot"],
            rec["lam_ev"],
            rec["lam_dep"],
        ]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(r, c, v)
            cell.font = BLUE_FONT if 6 <= c <= 12 else NORM
            cell.alignment = LEFT if c in (3, 4, 5, 18) else CENTER
            cell.border = THIN
            if c == 2:
                cell.number_format = "DD.MM.YYYY"
            if c in (6, 7, 8, 9, 10, 11, 12, 19, 20, 21):
                cell.number_format = "0.00"
            if r % 2 == 0 and c not in range(6, 13):
                cell.fill = PatternFill("solid", fgColor="F8FAFC")

    last = start + min(len(rows), cap) - 1
    note_row = start + cap + 1
    ws.cell(note_row, 1, f"{min(len(rows), cap)} maç yazıldı (kaynak football-data.co.uk, kapanış B365/Pinnacle). Motor satır 3–502 okur. KG yok — 2.5 ağırlığını Hedef'te artır.")
    ws.cell(note_row, 1).font = Font(name="Arial", size=9, italic=True, color="64748B")
    return min(len(rows), cap)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default="/home/workdir/artifacts/ATASU_Benzer_Oran_Motoru.xlsx")
    ap.add_argument("--dir", default="/home/workdir/artifacts/fd")
    ap.add_argument("--max", type=int, default=500)
    args = ap.parse_args()

    folder = Path(args.dir)
    files = sorted(folder.glob("*.csv"))
    if not files:
        raise SystemExit(f"CSV yok: {folder}")

    all_rows = []
    for f in files:
        part = load_csv(f)
        print(f"{f.name}: {len(part)} geçerli satır")
        all_rows.extend(part)

    # newest first so Motor 500 = en güncel
    all_rows.sort(key=lambda x: (x["date"], x["ev"]), reverse=True)
    # drop exact dupes
    seen = set()
    uniq = []
    for rec in all_rows:
        k = (rec["date"], rec["ev"], rec["dep"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(rec)
    print(f"toplam unique: {len(uniq)}")

    xlsx = Path(args.xlsx)
    wb = load_workbook(xlsx)
    if "Arsiv" not in wb.sheetnames:
        raise SystemExit("Arsiv sekmesi yok")
    n = write_arsiv(wb["Arsiv"], uniq, args.max)

    if "Kilavuz" in wb.sheetnames:
        k = wb["Kilavuz"]
        k["C26"] = f"ATASU-Benzer-1.1  |  fd.co.uk yüklendi {n} maç  |  {datetime.now():%Y-%m-%d %H:%M}"

    if "Hedef" in wb.sheetnames:
        h = wb["Hedef"]
        # leave sample target; user edits. bump note
        h["C22"] = (
            f"Arşiv güncel: {n} kapanış satırı (football-data.co.uk). "
            "KG boş — w_KG=0 veya 2.5 ağırlığını yükselt. λ kolonları implied beklenen gol (shot-xG değil)."
        )

    out = xlsx
    wb.save(out)
    print(f"yazıldı: {out}  ({n} satır)")


if __name__ == "__main__":
    main()
