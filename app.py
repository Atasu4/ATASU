from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
import json, re, sqlite3

ROOT = Path(__file__).parent
HISTORY = json.loads((ROOT / 'data/history.json').read_text(encoding='utf-8'))
DB = ROOT / 'data/codes.db'

MARKETS = [
    'h','d','a',
    'u25','o25',
    'btts','nobtts',
    'u35','o35',
    'iyu15','iyo15',
    'g6'
]

app = FastAPI(
    title='Profesyonel Oran + Kod +6 Analiz',
    version='2.0.0'
)

app.mount(
    '/static',
    StaticFiles(directory=ROOT / 'static'),
    name='static'
)


def init_db():
    with sqlite3.connect(DB) as c:
        c.execute(
            '''
            CREATE TABLE IF NOT EXISTS codes(
                code TEXT,
                league TEXT,
                home TEXT,
                away TEXT,
                ht TEXT,
                ft TEXT
            )
            '''
        )


init_db()


def score(s):
    m = re.fullmatch(
        r'\s*(\d+)\s*-\s*(\d+)\s*',
        str(s or '')
    )
    return (
        (int(m.group(1)), int(m.group(2)))
        if m else None
    )


def stats(rows):
    z = {
        k: 0 for k in [
            'home','draw','away',
            'o25','u25',
            'btts','nobtts',
            'o35','u35',
            'htHome','htDraw','htAway',
            'fh','sh','eq'
        ]
    }

    n = 0
    nh = 0

    for r in rows:
        ft = score(r.get('ft'))

        if not ft:
            continue

        n += 1
        h, a = ft
        total = h + a

        z[
            'home' if h > a
            else 'draw' if h == a
            else 'away'
        ] += 1

        z['o25' if total >= 3 else 'u25'] += 1
        z[
            'btts'
            if h > 0 and a > 0
            else 'nobtts'
        ] += 1
        z['o35' if total >= 4 else 'u35'] += 1

        ht = score(r.get('ht'))

        if ht:
            nh += 1
            x, y = ht

            z[
                'htHome'
                if x > y
                else 'htDraw'
                if x == y
                else 'htAway'
            ] += 1

            first_half = x + y
            second_half = total - first_half

            z[
                'fh'
                if first_half > second_half
                else 'sh'
                if second_half > first_half
                else 'eq'
            ] += 1

    def p(k, d):
        return round(100 * z[k] / d, 1) if d else None

    return {
        'sample_ft': n,
        'sample_ht': nh,

        'MS 1': p('home', n),
        'MS X': p('draw', n),
        'MS 2': p('away', n),

        '2,5 Üst': p('o25', n),
        '2,5 Alt': p('u25', n),

        'KG Var': p('btts', n),
        'KG Yok': p('nobtts', n),

        '3,5 Üst': p('o35', n),
        '3,5 Alt': p('u35', n),

        'İY 1': p('htHome', nh),
        'İY X': p('htDraw', nh),
        'İY 2': p('htAway', nh),

        'Daha çok gol 1.Y': p('fh', nh),
        'Daha çok gol 2.Y': p('sh', nh),
        'Yarılar eşit': p('eq', nh)
    }


# =========================================================
# ANA SAYFA
# =========================================================

@app.get('/')
def root():
    return FileResponse(ROOT / 'index.html')


@app.get('/api/meta')
def meta():
    return {
        'history_rows': len(HISTORY),
        'completed_rows': sum(
            score(x.get('ft')) is not None
            for x in HISTORY
        ),
        'markets': MARKETS,
        'rule': 'Only supplied/stored data are used.'
    }


# =========================================================
# ORAN ANALİZİ
# =========================================================

class OddsReq(BaseModel):
    odds: dict[str, float | None]
    tolerance: float = Field(0.05, ge=0, le=5)
    league: str = ''
    limit: int = Field(2000, ge=1, le=10000)


@app.post('/api/odds')
def odds(req: OddsReq):

    q = {}

    for k, v in req.odds.items():

        if k not in MARKETS or v is None:
            continue

        try:
            q[k] = float(v)
        except (TypeError, ValueError):
            pass

    if len(q) < 2:
        raise HTTPException(
            status_code=400,
            detail='Analiz için en az 2 desteklenen gerçek oran gerekli.'
        )

    pool = [
        r for r in HISTORY
        if score(r.get('ft'))
    ]

    if req.league.strip():

        league_query = req.league.strip().casefold()

        pool = [
            r for r in pool
            if league_query
            in str(r.get('league', '')).casefold()
        ]

    matches = []

    for r in pool:

        differences = {}
        valid = True

        for k, target in q.items():

            historical = r.get(k)

            if historical is None:
                valid = False
                break

            try:
                historical = float(historical)
            except (TypeError, ValueError):
                valid = False
                break

            diff = abs(
                historical - target
            )

            if diff > req.tolerance:
                valid = False
                break

            differences[k] = round(diff, 3)

        if valid:

            item = dict(r)

            item['_differences'] = differences

            item['_total_difference'] = round(
                sum(differences.values()),
                3
            )

            matches.append(item)

    matches.sort(
        key=lambda x:
        x.get('_total_difference', 999999)
    )

    total_matched = len(matches)

    shown = matches[:req.limit]

    return {
        'method':
            f'Girilen her desteklenen oran ayrı ayrı ±{req.tolerance} tolerans içinde eşleştirildi.',

        'searched_odds': q,

        'tolerance': req.tolerance,

        'pool_size': len(pool),

        'matched': total_matched,

        'returned': len(shown),

        # İSTATİSTİK TÜM EŞLEŞMELERDEN
        'stats': stats(matches),

        'matches': shown
    }


# =========================================================
# KOD VERİTABANI IMPORT
# =========================================================

class CodeImport(BaseModel):
    rows: list[dict]


@app.post('/api/codes/import')
def code_import(req: CodeImport):

    clean = []

    for r in req.rows:

        code = re.sub(
            r'\D',
            '',
            str(r.get('code', ''))
        )

        if not re.fullmatch(r'\d{5}', code):
            continue

        clean.append(
            (
                code,
                str(r.get('league', '')),
                str(r.get('home', '')),
                str(r.get('away', '')),
                str(r.get('ht', '')),
                str(r.get('ft', ''))
            )
        )

    with sqlite3.connect(DB) as c:

        c.execute('DELETE FROM codes')

        c.executemany(
            'INSERT INTO codes VALUES(?,?,?,?,?,?)',
            clean
        )

    return {
        'saved': len(clean)
    }


# =========================================================
# TEK KOD TARAMA
# =========================================================

class CodeReq(BaseModel):
    code: str
    direction: str = 'exact'
    digits: int = Field(5, ge=1, le=5)
    league: str = ''


def load_codes():

    with sqlite3.connect(DB) as c:

        rows = [
            dict(
                zip(
                    [
                        'code',
                        'league',
                        'home',
                        'away',
                        'ht',
                        'ft'
                    ],
                    x
                )
            )
            for x in c.execute(
                'SELECT * FROM codes'
            )
        ]

    return rows


def code_matches(
    stored_code,
    search_code,
    direction,
    digits
):

    if direction == 'exact':
        return stored_code == search_code

    if direction == 'start':
        return stored_code.startswith(
            search_code[:digits]
        )

    if direction == 'end':
        return stored_code.endswith(
            search_code[-digits:]
        )

    return False


@app.post('/api/code')
def code_scan(req: CodeReq):

    code = re.sub(
        r'\D',
        '',
        req.code
    )

    if not re.fullmatch(r'\d{5}', code):

        raise HTTPException(
            400,
            'Kod tam 5 haneli olmalı.'
        )

    rows = load_codes()

    found = []

    for r in rows:

        if not code_matches(
            r['code'],
            code,
            req.direction,
            req.digits
        ):
            continue

        if (
            req.league.strip()
            and req.league.casefold()
            not in r['league'].casefold()
        ):
            continue

        found.append(r)

    return {
        'stored': len(rows),
        'matched': len(found),
        'searched_code': code,
        'stats': stats(found),
        'matches': found
    }


# =========================================================
# TOPLU KOD TARAMA
# =========================================================

class BulkCodeReq(BaseModel):
    codes: list[str]
    direction: str = 'exact'
    digits: int = Field(5, ge=1, le=5)
    league: str = ''


@app.post('/api/codes/scan')
def bulk_code_scan(req: BulkCodeReq):

    search_codes = []

    for raw in req.codes:

        code = re.sub(
            r'\D',
            '',
            str(raw)
        )

        if re.fullmatch(r'\d{5}', code):
            search_codes.append(code)

    # Tekrarlanan kodları kaldır
    search_codes = list(
        dict.fromkeys(search_codes)
    )

    if not search_codes:

        raise HTTPException(
            400,
            'Geçerli 5 haneli kod bulunamadı.'
        )

    rows = load_codes()

    all_matches = []

    results = []

    for code in search_codes:

        found = []

        for r in rows:

            if not code_matches(
                r['code'],
                code,
                req.direction,
                req.digits
            ):
                continue

            if (
                req.league.strip()
                and req.league.casefold()
                not in r['league'].casefold()
            ):
                continue

            found.append(r)

        results.append({
            'code': code,
            'matched': len(found),
            'stats': stats(found),
            'matches': found
        })

        all_matches.extend(found)

    # Aynı geçmiş kayıt birden fazla kod tarafından
    # yakalanırsa genel istatistikte bir kez say.
    unique = []
    seen = set()

    for r in all_matches:

        key = (
            r.get('code'),
            r.get('league'),
            r.get('home'),
            r.get('away'),
            r.get('ht'),
            r.get('ft')
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(r)

    return {
        'stored': len(rows),

        'searched_count':
            len(search_codes),

        'searched_codes':
            search_codes,

        'matched_total':
            len(unique),

        'stats':
            stats(unique),

        'results':
            results,

        'matches':
            unique
    }


# =========================================================
# +6 REFERANS MOTORU
# =========================================================

class Plus6Req(BaseModel):
    o25: float | None = None
    o35: float | None = None
    o45: float | None = None
    btts: float | None = None
    iy05: float | None = None
    nofirst: float | None = None


@app.post('/api/plus6')
def plus6(q: Plus6Req):

    rules = [
        (
            '2,5 Üst',
            q.o25,
            1.20,
            1.28
        ),
        (
            '3,5 Üst',
            q.o35,
            1.66,
            1.89
        ),
        (
            '4,5 Üst',
            q.o45,
            2.64,
            3.14
        ),
        (
            'KG Var',
            q.btts,
            1.22,
            1.87
        )
    ]

    out = []
    hit = 0

    for name, val, lo, hi in rules:

        ok = (
            val is not None
            and lo <= val <= hi
        )

        hit += int(ok)

        out.append({
            'name': name,
            'value': val,
            'range': [lo, hi],
            'match': ok
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

    hit += int(last)

    out.append({
        'name':
            'İY 0,5 Üst veya İlk Gol/Korner Olmaz',

        'values':
            [q.iy05, q.nofirst],

        'ranges':
            [
                [1.05, 1.08],
                [22.10, 26.00]
            ],

        'match':
            last
    })

    return {
        'matched_rules': hit,
        'total_rules': 5,
        'compatibility_percent':
            hit * 20,
        'rules': out,
        'note':
            'Bu yalnızca kullanıcının verdiği +6 referans bantlarına uyum oranıdır; tahmin değildir.'
    }
