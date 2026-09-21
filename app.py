from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
import json, re, sqlite3

ROOT=Path(__file__).parent
HISTORY=json.loads((ROOT/'data/history.json').read_text(encoding='utf-8'))
DB=ROOT/'data/codes.db'
MARKETS=['h','d','a','u25','o25','btts','nobtts','u35','o35','iyu15','iyo15','g6']
app=FastAPI(title='Profesyonel Oran + Kod +6 Analiz',version='1.0.0')
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

def init_db():
    with sqlite3.connect(DB) as c:
        c.execute('CREATE TABLE IF NOT EXISTS codes(code TEXT, league TEXT, home TEXT, away TEXT, ht TEXT, ft TEXT)')
init_db()

def score(s):
    m=re.fullmatch(r'\s*(\d+)\s*-\s*(\d+)\s*',str(s or ''))
    return (int(m.group(1)),int(m.group(2))) if m else None

def stats(rows):
    z={k:0 for k in ['home','draw','away','o25','u25','btts','nobtts','o35','u35','htHome','htDraw','htAway','fh','sh','eq']}; n=nh=0
    for r in rows:
        ft=score(r.get('ft'))
        if not ft: continue
        n+=1; h,a=ft; t=h+a
        z['home' if h>a else 'draw' if h==a else 'away']+=1
        z['o25' if t>=3 else 'u25']+=1; z['btts' if h>0 and a>0 else 'nobtts']+=1; z['o35' if t>=4 else 'u35']+=1
        ht=score(r.get('ht'))
        if ht:
            nh+=1; x,y=ht; z['htHome' if x>y else 'htDraw' if x==y else 'htAway']+=1
            f=x+y; s=t-f; z['fh' if f>s else 'sh' if s>f else 'eq']+=1
    def p(k,d): return round(100*z[k]/d,1) if d else None
    return {'sample_ft':n,'sample_ht':nh,'MS 1':p('home',n),'MS X':p('draw',n),'MS 2':p('away',n),'2,5 Üst':p('o25',n),'2,5 Alt':p('u25',n),'KG Var':p('btts',n),'KG Yok':p('nobtts',n),'3,5 Üst':p('o35',n),'3,5 Alt':p('u35',n),'İY 1':p('htHome',nh),'İY X':p('htDraw',nh),'İY 2':p('htAway',nh),'Daha çok gol 1.Y':p('fh',nh),'Daha çok gol 2.Y':p('sh',nh),'Yarılar eşit':p('eq',nh)}

class OddsReq(BaseModel):
    odds: dict[str,float|None]
    tolerance: float=Field(0.05,ge=0,le=5)
    league: str=''
    limit: int=Field(200,ge=1,le=2000)

@app.get('/')
def root(): return FileResponse(ROOT/index.html')

@app.get('/api/meta')
def meta():
    return {'history_rows':len(HISTORY),'completed_rows':sum(score(x.get('ft')) is not None for x in HISTORY),'markets':MARKETS,'rule':'Only supplied/stored data are used.'}

@app.post('/api/odds')
def odds(req:OddsReq):
    q={k:float(v) for k,v in req.odds.items() if k in MARKETS and v is not None}
    if len(q)<2: raise HTTPException(400,'En az 2 gerçek oran girilmeli.')
    pool=[r for r in HISTORY if score(r.get('ft'))]
    if req.league.strip(): pool=[r for r in pool if req.league.casefold() in str(r.get('league','')).casefold()]
    matches=[]
    for r in pool:
        if not all(r.get(k) is not None and abs(float(r[k])-v)<=req.tolerance for k,v in q.items()): continue
        matches.append(r)
    matches=matches[:req.limit]
    return {'method':f'Girilen her oranda mutlak ±{req.tolerance:.2f} tolerans; gizli puanlama yok.','entered_markets':q,'scanned':len(pool),'matched_total':sum(1 for r in pool if all(r.get(k) is not None and abs(float(r[k])-v)<=req.tolerance for k,v in q.items())),'returned':len(matches),'stats':stats(matches),'matches':matches[:100]}

class CodeImport(BaseModel): rows:list[dict]
@app.post('/api/codes/import')
def code_import(req:CodeImport):
    clean=[]
    for r in req.rows:
        code=re.sub(r'\D','',str(r.get('code','')))
        if not re.fullmatch(r'\d{5}',code): continue
        clean.append((code,str(r.get('league','')),str(r.get('home','')),str(r.get('away','')),str(r.get('ht','')),str(r.get('ft',''))))
    with sqlite3.connect(DB) as c:
        c.execute('DELETE FROM codes'); c.executemany('INSERT INTO codes VALUES(?,?,?,?,?,?)',clean)
    return {'saved':len(clean)}

class CodeReq(BaseModel): code:str; direction:str='exact'; digits:int=Field(5,ge=1,le=5); league:str=''
@app.post('/api/code')
def code_scan(req:CodeReq):
    code=re.sub(r'\D','',req.code)
    if not re.fullmatch(r'\d{5}',code): raise HTTPException(400,'Kod tam 5 haneli olmalı.')
    with sqlite3.connect(DB) as c:
        rows=[dict(zip(['code','league','home','away','ht','ft'],x)) for x in c.execute('SELECT * FROM codes')]
    needle=code if req.direction=='exact' else code[:req.digits] if req.direction=='start' else code[-req.digits:]
    def ok(r):
        c=r['code']; hit=c==needle if req.direction=='exact' else c.startswith(needle) if req.direction=='start' else c.endswith(needle)
        return hit and (not req.league.strip() or req.league.casefold() in r['league'].casefold())
    found=[r for r in rows if ok(r)]
    return {'stored':len(rows),'matched':len(found),'needle':needle,'stats':stats(found),'matches':found[:100]}

class Plus6Req(BaseModel): o25:float|None=None; o35:float|None=None; o45:float|None=None; btts:float|None=None; iy05:float|None=None; nofirst:float|None=None
@app.post('/api/plus6')
def plus6(q:Plus6Req):
    rules=[('2,5 Üst',q.o25,1.20,1.28),('3,5 Üst',q.o35,1.66,1.89),('4,5 Üst',q.o45,2.64,3.14),('KG Var',q.btts,1.22,1.87)]
    out=[]; hit=0
    for name,val,lo,hi in rules:
        ok=val is not None and lo<=val<=hi; hit+=int(ok); out.append({'name':name,'value':val,'range':[lo,hi],'match':ok})
    last=(q.iy05 is not None and 1.05<=q.iy05<=1.08) or (q.nofirst is not None and 22.10<=q.nofirst<=26.00)
    hit+=int(last); out.append({'name':'İY 0,5 Üst veya İlk Gol/Korner Olmaz','values':[q.iy05,q.nofirst],'ranges':[[1.05,1.08],[22.10,26.00]],'match':last})
    return {'matched_rules':hit,'total_rules':5,'compatibility_percent':hit*20,'rules':out,'note':'Bu yalnızca kullanıcının verdiği +6 referans bantlarına uyum oranıdır; tahmin değildir.'}
