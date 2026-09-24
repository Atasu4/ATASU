from __future__ import annotations
import hashlib, json, re, sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def norm(v):
    s=str(v or '').casefold().translate(str.maketrans('ığüşöç','igusoc'))
    return ' '.join(re.findall(r'[a-z0-9]+',s))
def teams(title):
    for sep in (' vs ',' VS ',' v ',' — ',' – ',' - '):
        if sep in str(title or ''):
            a,b=str(title).split(sep,1); return a.strip(),b.strip()
    return '',''
def won(key,ft):
    m=re.fullmatch(r'\s*(\d+)\s*[-–]\s*(\d+)\s*',str(ft or ''))
    if not m:return None
    h,a=map(int,m.groups());t=h+a
    return {'h':h>a,'d':h==a,'a':h<a,'o25':t>=3,'u25':t<=2,'o35':t>=4,'u35':t<=3,'btts':h>0 and a>0,'nobtts':h==0 or a==0,'g6':t>=6,'g45':t>=5}.get(key)
class PredictionStore:
    def __init__(self,path): self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.init()
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=20);c.row_factory=sqlite3.Row;c.execute('PRAGMA journal_mode=WAL')
        try: yield c;c.commit()
        except: c.rollback();raise
        finally:c.close()
    def init(self):
        with self.db() as c:c.executescript("""CREATE TABLE IF NOT EXISTS predictions(id INTEGER PRIMARY KEY,fingerprint TEXT UNIQUE,created_at TEXT,model_version TEXT,match_title TEXT,home TEXT,away TEXT,market_key TEXT,selection TEXT,odds REAL,confidence REAL,edge_points REAL,sample_size INTEGER,status TEXT DEFAULT 'open',result_ft TEXT,settled_at TEXT,profit_units REAL,evidence_json TEXT);CREATE INDEX IF NOT EXISTS ix_status ON predictions(status);""")
    def add_prediction(self,**x):
        h,a=teams(x.get('title'));fp=hashlib.sha256('|'.join([norm(h),norm(a),str(x.get('market_key')),str(x.get('model_version'))]).encode()).hexdigest()
        with self.db() as c:
            c.execute("INSERT OR IGNORE INTO predictions(fingerprint,created_at,model_version,match_title,home,away,market_key,selection,odds,confidence,edge_points,sample_size,evidence_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(fp,now(),x.get('model_version','7.1.0'),x.get('title',''),h,a,x.get('market_key'),x.get('selection'),float(x.get('odds')),x.get('confidence'),x.get('edge_points'),x.get('sample_size'),json.dumps(x.get('evidence') or {},ensure_ascii=False)))
            created=bool(c.execute('SELECT changes()').fetchone()[0]);row=dict(c.execute('SELECT * FROM predictions WHERE fingerprint=?',(fp,)).fetchone());return row,created
    def settle(self,prediction_id,won=None,odds=None,ft=None,source='manual'):
        with self.db() as c:
            r=c.execute('SELECT * FROM predictions WHERE id=?',(prediction_id,)).fetchone()
            if not r:return None
            if r['status']!='open':return dict(r)
            status='won' if won else 'lost';profit=round(float(odds or r['odds'])-1,4) if won else -1.0
            c.execute('UPDATE predictions SET status=?,result_ft=?,settled_at=?,profit_units=? WHERE id=?',(status,ft,now(),profit,prediction_id));return dict(c.execute('SELECT * FROM predictions WHERE id=?',(prediction_id,)).fetchone())
    def auto_settle(self,history):
        with self.db() as c: rows=[dict(r) for r in c.execute("SELECT * FROM predictions WHERE status='open'")]
        out=[]
        for p in rows:
            hits=[r for r in history if norm(r.get('home'))==norm(p['home']) and norm(r.get('away'))==norm(p['away']) and r.get('ft')]
            if len(hits)==1:
                w=won(p['market_key'],hits[0]['ft'])
                if w is not None:out.append(self.settle(p['id'],w,ft=hits[0]['ft'],source='history'))
        return out
    def summary(self,limit=100):
        with self.db() as c:
            total=c.execute('SELECT COUNT(*) FROM predictions').fetchone()[0];settled=c.execute("SELECT COUNT(*) FROM predictions WHERE status IN ('won','lost')").fetchone()[0];wins=c.execute("SELECT COUNT(*) FROM predictions WHERE status='won'").fetchone()[0];profit=c.execute("SELECT COALESCE(SUM(profit_units),0) FROM predictions WHERE status IN ('won','lost')").fetchone()[0];recent=[dict(r) for r in c.execute('SELECT * FROM predictions ORDER BY id DESC LIMIT ?',(limit,))]
        return {'total_predictions':total,'settled':settled,'wins':wins,'losses':settled-wins,'hit_rate':round(100*wins/settled,1) if settled else None,'profit_units':round(profit,2),'roi_percent':round(100*profit/settled,1) if settled else None,'recent':recent}
