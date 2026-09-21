from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
import json
import re
import sqlite3

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
HISTORY_FILE = DATA_DIR / "history.json"
DB = DATA_DIR / "codes.db"

if not HISTORY_FILE.exists():
    raise RuntimeError("data/history.json bulunamadı.")

HISTORY = json.loads(
    HISTORY_FILE.read_text(encoding="utf-8")
)

MARKETS = [
    "h", "d", "a",
    "u25", "o25",
    "btts", "nobtts",
    "u35", "o35",
    "iyu15", "iyo15",
    "g6"
]

app = FastAPI(
    title="ATASU Analiz",
    version="2.0.0"
)

static_dir = ROOT / "static"

if static_dir.exists():
    app.mount(
        "/static",
        StaticFiles(directory=static_dir),
        name="static"
    )


# =========================================================
# DATABASE
# =========================================================

def init_db():
    DATA_DIR.mkdir(exist_ok=True)

    with sqlite3.connect(DB) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS codes(
                code TEXT,
                league TEXT,
                home TEXT,
                away TEXT,
                ht TEXT,
                ft TEXT
            )
        """)


init_db()


# =========================================================
# HELPERS
# =========================================================

def score(value):
    m = re.fullmatch(
        r"\s*(\d+)\s*-\s*(\d+)\s*",
        str(value or "")
    )

    if not m:
        return None

    return int(m.group(1)), int(m.group(2))


def stats(rows):

    z = {
        "home": 0,
        "draw": 0,
        "away": 0,

        "o25": 0,
        "u25": 0,

        "btts": 0,
        "nobtts": 0,

        "o35": 0,
        "u35": 0,

        "htHome": 0,
        "htDraw": 0,
        "htAway": 0,

        "fh": 0,
        "sh": 0,
        "eq": 0
    }

    n = 0
    nh = 0

    for r in rows:

        ft = score(r.get("ft"))

        if not ft:
            continue

        n += 1

        home_goals, away_goals = ft
        total = home_goals + away_goals

        if home_goals > away_goals:
            z["home"] += 1

        elif home_goals == away_goals:
            z["draw"] += 1

        else:
            z["away"] += 1

        if total >= 3:
            z["o25"] += 1
        else:
            z["u25"] += 1

        if home_goals > 0 and away_goals > 0:
            z["btts"] += 1
        else:
            z["nobtts"] += 1

        if total >= 4:
            z["o35"] += 1
        else:
            z["u35"] += 1

        ht = score(r.get("ht"))

        if ht:

            nh += 1

            ht_home, ht_away = ht

            if ht_home > ht_away:
                z["htHome"] += 1

            elif ht_home == ht_away:
                z["htDraw"] += 1

            else:
                z["htAway"] += 1

            first_half = ht_home + ht_away
            second_half = total - first_half

            if first_half > second_half:
                z["fh"] += 1

            elif second_half > first_half:
                z["sh"] += 1

            else:
                z["eq"] += 1

    def pct(key, denominator):

        if not denominator:
            return None

        return round(
            100 * z[key] / denominator,
            1
        )

    return {
        "sample_ft": n,
        "sample_ht": nh,

        "MS 1": pct("home", n),
        "MS X": pct("draw", n),
        "MS 2": pct("away", n),

        "2,5 Üst": pct("o25", n),
        "2,5 Alt": pct("u25", n),

        "KG Var": pct("btts", n),
        "KG Yok": pct("nobtts", n),

        "3,5 Üst": pct("o35", n),
        "3,5 Alt": pct("u35", n),

        "İY 1": pct("htHome", nh),
        "İY X": pct("htDraw", nh),
        "İY 2": pct("htAway", nh),

        "Daha çok gol 1.Y": pct("fh", nh),
        "Daha çok gol 2.Y": pct("sh", nh),
        "Yarılar eşit": pct("eq", nh)
    }


# =========================================================
# HOME
# =========================================================

@app.get("/")
def root():
    return FileResponse(ROOT / "index.html")


@app.get("/api/meta")
def meta():

    completed = sum(
        score(x.get("ft")) is not None
        for x in HISTORY
    )

    with sqlite3.connect(DB) as c:
        stored_codes = c.execute(
            "SELECT COUNT(*) FROM codes"
        ).fetchone()[0]

    return {
        "history_rows": len(HISTORY),
        "completed_rows": completed,
        "stored_codes": stored_codes,
        "markets": MARKETS,
        "rule": "Only supplied/stored real data are used."
    }


# =========================================================
# ODDS
# =========================================================

class OddsReq(BaseModel):
    odds: dict[str, float | None]
    tolerance: float = Field(
        0.05,
        ge=0,
        le=5
    )
    league: str = ""
    limit: int = Field(
        10000,
        ge=1,
        le=50000
    )


@app.post("/api/odds")
def odds_scan(req: OddsReq):

    q = {}

    for key, value in req.odds.items():
        if key not in MARKETS or value is None:
            continue
        try:
            q[key] = float(value)
        except (TypeError, ValueError):
            continue

    if len(q) < 2:
        raise HTTPException(
            status_code=400,
            detail="En az 2 desteklenen gerçek oran bulunmalı."
        )

    pool = [
        r for r in HISTORY
        if score(r.get("ft")) is not None
    ]

    if req.league.strip():
        league_query = req.league.strip().casefold()
        pool = [
            r for r in pool
            if league_query in str(r.get("league", "")).casefold()
        ]

    candidates = []

    for row in pool:
        differences = {}
        matched_differences = {}
        compared = 0
        matched_count = 0

        for key, target in q.items():
            historical = row.get(key)

            if historical is None:
                continue

            try:
                historical = float(historical)
            except (TypeError, ValueError):
                continue

            compared += 1
            diff = abs(historical - target)
            differences[key] = round(diff, 3)

            if diff <= req.tolerance:
                matched_count += 1
                matched_differences[key] = round(diff, 3)

        if compared < 2:
            continue

        item = dict(row)
        item["_matched_odds"] = matched_count
        item["_compared_odds"] = compared
        item["_match_ratio"] = round(
            matched_count / compared * 100,
            1
        )
        item["_differences"] = differences
        item["_matched_differences"] = matched_differences
        item["_total_difference"] = round(
            sum(differences.values()),
            3
        )

        candidates.append(item)

    searched_count = len(q)

    minimum_match_count = max(
        2,
        (searched_count + 1) // 2
    )

    matches = [
        x for x in candidates
        if x["_matched_odds"] >= minimum_match_count
    ]

    fallback = False

    if not matches and candidates:
        best_match_count = max(
            x["_matched_odds"]
            for x in candidates
        )

        if best_match_count > 0:
            matches = [
                x for x in candidates
                if x["_matched_odds"] == best_match_count
            ]
            fallback = True

    matches.sort(
        key=lambda x: (
            -x["_matched_odds"],
            -x["_match_ratio"],
            x["_total_difference"]
        )
    )

    total_matches = len(matches)
    returned_matches = matches[:req.limit]

    best_match_count = (
        matches[0]["_matched_odds"]
        if matches else 0
    )

    if fallback:
        method = (
            f"{searched_count} oran tarandı. "
            f"En güçlü gerçek eşleşmeler gösteriliyor. "
            f"En yüksek eşleşme: "
            f"{best_match_count}/{searched_count}."
        )
    else:
        method = (
            f"{searched_count} oran tarandı. "
            f"En az {minimum_match_count}/{searched_count} oranı "
            f"±{req.tolerance} içinde eşleşen maçlar gösteriliyor. "
            f"En güçlü eşleşme: "
            f"{best_match_count}/{searched_count}."
        )

    return {
        "method": method,
        "searched_odds": q,
        "searched_count": searched_count,
        "tolerance": req.tolerance,
        "pool_size": len(pool),
        "matched": total_matches,
        "returned": len(returned_matches),
        "minimum_match_count": minimum_match_count,
        "best_match_count": best_match_count,
        "stats": stats(matches),
        "matches": returned_matches
    }


# =========================================================
# CODE IMPORT
# =========================================================

class CodeImport(BaseModel):
    rows: list[dict]


@app.post("/api/codes/import")
def code_import(req: CodeImport):

    clean = []

    for r in req.rows:

        code = re.sub(
            r"\D",
            "",
            str(r.get("code", ""))
        )

        if not re.fullmatch(
            r"\d{5}",
            code
        ):
            continue

        clean.append((
            code,
            str(r.get("league", "")),
            str(r.get("home", "")),
            str(r.get("away", "")),
            str(r.get("ht", "")),
            str(r.get("ft", ""))
        ))

    with sqlite3.connect(DB) as c:

        c.execute(
            "DELETE FROM codes"
        )

        c.executemany(
            """
            INSERT INTO codes
            VALUES(?,?,?,?,?,?)
            """,
            clean
        )

    return {
        "saved": len(clean)
    }


# =========================================================
# SINGLE CODE
# =========================================================

class CodeReq(BaseModel):
    code: str
    direction: str = "exact"
    digits: int = Field(
        5,
        ge=1,
        le=5
    )
    league: str = ""


@app.post("/api/code")
def code_scan(req: CodeReq):

    result = scan_codes_internal(
        [req.code],
        req.direction,
        req.digits,
        req.league
    )

    if not result["results"]:
        return {
            "stored": result["stored"],
            "matched": 0,
            "stats": stats([]),
            "matches": []
        }

    first = result["results"][0]

    return {
        "stored": result["stored"],
        "matched": first["matched"],
        "stats": first["stats"],
        "matches": first["matches"]
    }


# =========================================================
# BULK CODE
# =========================================================

class CodesReq(BaseModel):
    codes: list[str]
    direction: str = "exact"
    digits: int = Field(
        5,
        ge=1,
        le=5
    )
    league: str = ""


def scan_codes_internal(
    supplied_codes,
    direction,
    digits,
    league
):

    if direction not in {
        "exact",
        "start",
        "end"
    }:
        raise HTTPException(
            status_code=400,
            detail="Geçersiz kod eşleşme yönü."
        )

    clean_codes = []

    for value in supplied_codes:

        code = re.sub(
            r"\D",
            "",
            str(value)
        )

        if re.fullmatch(
            r"\d{5}",
            code
        ):
            clean_codes.append(code)

    clean_codes = list(
        dict.fromkeys(clean_codes)
    )

    if not clean_codes:
        raise HTTPException(
            status_code=400,
            detail="Geçerli 5 haneli kod bulunamadı."
        )

    with sqlite3.connect(DB) as c:

        db_rows = [
            dict(
                zip(
                    [
                        "code",
                        "league",
                        "home",
                        "away",
                        "ht",
                        "ft"
                    ],
                    row
                )
            )
            for row in c.execute(
                "SELECT * FROM codes"
            )
        ]

    league_query = (
        league.strip().casefold()
    )

    if league_query:

        db_rows = [
            r for r in db_rows
            if league_query in
            str(
                r.get("league", "")
            ).casefold()
        ]

    results = []
    all_matches = []

    for supplied in clean_codes:

        if direction == "exact":

            needle = supplied

        elif direction == "start":

            needle = supplied[:digits]

        else:

            needle = supplied[-digits:]

        found = []

        for row in db_rows:

            stored_code = str(
                row.get("code", "")
            )

            if direction == "exact":

                hit = (
                    stored_code == supplied
                )

            elif direction == "start":

                hit = stored_code.startswith(
                    needle
                )

            else:

                hit = stored_code.endswith(
                    needle
                )

            if hit:
                found.append(row)
                all_matches.append(row)

        results.append({
            "code": supplied,
            "needle": needle,
            "matched": len(found),
            "stats": stats(found),
            "matches": found
        })

    return {
        "stored": len(db_rows),
        "searched_count": len(clean_codes),
        "searched_codes": clean_codes,
        "matched_total": len(all_matches),
        "stats": stats(all_matches),
        "results": results
    }


@app.post("/api/codes/scan")
def codes_scan(req: CodesReq):

    return scan_codes_internal(
        req.codes,
        req.direction,
        req.digits,
        req.league
    )


# =========================================================
# +6 ANALYSIS
# =========================================================

class Plus6Req(BaseModel):
    o25: float | None = None
    o35: float | None = None
    o45: float | None = None
    btts: float | None = None
    iy05: float | None = None
    nofirst: float | None = None


@app.post("/api/plus6")
def plus6(q: Plus6Req):

    rules = [
        (
            "2,5 Üst",
            q.o25,
            1.20,
            1.28
        ),
        (
            "3,5 Üst",
            q.o35,
            1.66,
            1.89
        ),
        (
            "4,5 Üst",
            q.o45,
            2.64,
            3.14
        ),
        (
            "KG Var",
            q.btts,
            1.22,
            1.87
        )
    ]

    output = []
    hit = 0

    for name, value, lo, hi in rules:

        matched = (
            value is not None
            and lo <= value <= hi
        )

        if matched:
            hit += 1

        output.append({
            "name": name,
            "value": value,
            "range": [lo, hi],
            "match": matched
        })

    last = (
        (
            q.iy05 is not None
            and 1.05 <= q.iy05 <= 1.08
        )
        or
        (
            q.nofirst is not None
            and 22.10 <= q.nofirst <= 26.00
        )
    )

    if last:
        hit += 1

    output.append({
        "name":
            "İY 0,5 Üst veya İlk Gol Olmaz",

        "values": [
            q.iy05,
            q.nofirst
        ],

        "ranges": [
            [1.05, 1.08],
            [22.10, 26.00]
        ],

        "match": last
    })

    return {
        "matched_rules": hit,
        "total_rules": 5,
        "compatibility_percent":
            round(hit / 5 * 100),
        "rules": output,
        "note":
            "Bu bölüm yalnızca kayıtlı +6 referans "
            "bantlarıyla karşılaştırmadır."
    }
