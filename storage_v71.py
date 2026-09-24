"""ATASU V7.1 SQLite storage, duplicate protection and automatic settlement."""
from __future__ import annotations
import hashlib, json, re, sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 2


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm_text(value):
    s = str(value or "").casefold()
    s = s.replace("ı", "i").replace("ğ", "g").replace("ü", "u").replace("ş", "s").replace("ö", "o").replace("ç", "c")
    return " ".join(re.findall(r"[a-z0-9]+", s))


def parse_teams(title):
    t = re.split(r"\s*\|\s*|\s+-\s+Mackolik", str(title or ""), maxsplit=1)[0]
    for sep in (" vs ", " VS ", " v ", " — ", " – ", " - "):
        if sep in t:
            a, b = t.split(sep, 1)
            if a.strip() and b.strip():
                return a.strip(), b.strip()
    return "", ""


def market_won(key, ft):
    m = re.fullmatch(r"\s*(\d+)\s*[-–]\s*(\d+)\s*", str(ft or ""))
    if not m:
        return None
    h, a = int(m.group(1)), int(m.group(2)); total = h + a
    return {"h": h > a, "d": h == a, "a": h < a, "o25": total >= 3, "u25": total <= 2,
            "o35": total >= 4, "u35": total <= 3, "btts": h > 0 and a > 0,
            "nobtts": h == 0 or a == 0, "g6": total >= 6, "g45": total >= 5}.get(key)


class PredictionStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=20)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback(); raise
        finally:
            con.close()

    def init_db(self):
        with self.connect() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS predictions(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              fingerprint TEXT NOT NULL UNIQUE,
              created_at TEXT NOT NULL,
              model_version TEXT NOT NULL,
              match_title TEXT NOT NULL,
              home TEXT, away TEXT, match_date TEXT,
              market_key TEXT NOT NULL, selection TEXT NOT NULL,
              odds REAL NOT NULL CHECK(odds > 1), confidence REAL,
              edge_points REAL, sample_size INTEGER,
              status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','won','lost','void')),
              result_ft TEXT, settled_at TEXT, profit_units REAL,
              evidence_json TEXT NOT NULL DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS ix_predictions_status ON predictions(status);
            CREATE INDEX IF NOT EXISTS ix_predictions_teams ON predictions(home,away);
            CREATE TABLE IF NOT EXISTS match_history(
              fingerprint TEXT PRIMARY KEY, match_date TEXT, league TEXT, home TEXT NOT NULL, away TEXT NOT NULL,
              ht TEXT, ft TEXT, payload_json TEXT NOT NULL, imported_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_history_teams ON match_history(home,away);
            CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settlement_audit(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              prediction_id INTEGER NOT NULL REFERENCES predictions(id),
              created_at TEXT NOT NULL, old_status TEXT, new_status TEXT NOT NULL,
              result_ft TEXT, source TEXT NOT NULL
            );
            """)
            c.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
            c.execute("INSERT OR IGNORE INTO migrations(version,applied_at) VALUES(?,?)", (SCHEMA_VERSION,utcnow()))

    def add_prediction(self, *, title, market_key, selection, odds, confidence=None, edge_points=None,
                       sample_size=None, evidence=None, model_version="7.1.0", match_date=None):
        home, away = parse_teams(title)
        identity = "|".join([norm_text(home), norm_text(away), str(match_date or ""), market_key, model_version])
        fingerprint = hashlib.sha256(identity.encode()).hexdigest()
        with self.connect() as c:
            c.execute("""INSERT OR IGNORE INTO predictions
              (fingerprint,created_at,model_version,match_title,home,away,match_date,market_key,selection,odds,confidence,edge_points,sample_size,evidence_json)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (fingerprint,utcnow(),model_version,title,home,away,match_date,market_key,selection,float(odds),confidence,edge_points,sample_size,json.dumps(evidence or [],ensure_ascii=False)))
            row=c.execute("SELECT * FROM predictions WHERE fingerprint=?",(fingerprint,)).fetchone()
            return dict(row), bool(c.execute("SELECT changes()").fetchone()[0])

    def settle(self, prediction_id, won=None, odds=None, ft=None, source="manual", void=False):
        with self.connect() as c:
            row=c.execute("SELECT * FROM predictions WHERE id=?",(prediction_id,)).fetchone()
            if not row: return None
            if row["status"] != "open": return dict(row)
            status="void" if void else ("won" if won else "lost")
            use_odds=float(odds or row["odds"])
            profit=None if void else round(use_odds-1,4) if won else -1.0
            c.execute("UPDATE predictions SET status=?,result_ft=?,settled_at=?,profit_units=? WHERE id=?",(status,ft,utcnow(),profit,prediction_id))
            c.execute("INSERT INTO settlement_audit(prediction_id,created_at,old_status,new_status,result_ft,source) VALUES(?,?,?,?,?,?)",(prediction_id,utcnow(),row["status"],status,ft,source))
            return dict(c.execute("SELECT * FROM predictions WHERE id=?",(prediction_id,)).fetchone())

    def auto_settle(self, history):
        settled=[]
        with self.connect() as c:
            opens=[dict(x) for x in c.execute("SELECT * FROM predictions WHERE status='open'").fetchall()]
        for p in opens:
            ph, pa = norm_text(p["home"]), norm_text(p["away"])
            candidates=[]
            for r in history:
                if norm_text(r.get("home"))==ph and norm_text(r.get("away"))==pa and r.get("ft"):
                    if p.get("match_date") and str(r.get("date") or "") != p["match_date"]: continue
                    candidates.append(r)
            if len(candidates) != 1: continue
            won=market_won(p["market_key"],candidates[0].get("ft"))
            if won is None: continue
            settled.append(self.settle(p["id"],won=won,ft=candidates[0].get("ft"),source="history.json"))
        return settled

    def import_history(self, rows):
        added=updated=0
        with self.connect() as c:
            for r in rows or []:
                home,away=str(r.get("home") or ""),str(r.get("away") or "")
                if not home or not away: continue
                raw="|".join([str(r.get("date") or ""),norm_text(home),norm_text(away),str(r.get("ft") or "")])
                fp=hashlib.sha256(raw.encode()).hexdigest()
                exists=c.execute("SELECT 1 FROM match_history WHERE fingerprint=?",(fp,)).fetchone()
                c.execute("""INSERT OR REPLACE INTO match_history(fingerprint,match_date,league,home,away,ht,ft,payload_json,imported_at)
                    VALUES(?,?,?,?,?,?,?,?,?)""",(fp,r.get("date"),r.get("league"),home,away,r.get("ht"),r.get("ft"),json.dumps(r,ensure_ascii=False),utcnow()))
                if exists: updated+=1
                else: added+=1
        return {"added":added,"updated":updated,"total":self.history_count()}

    def history_count(self):
        with self.connect() as c: return c.execute("SELECT COUNT(*) FROM match_history").fetchone()[0]

    def load_history(self):
        with self.connect() as c:
            return [json.loads(x[0]) for x in c.execute("SELECT payload_json FROM match_history ORDER BY match_date").fetchall()]

    def list_predictions(self, *, status="", market="", model_version="", date_from="", date_to="", query="", limit=100, offset=0):
        wh=[]; args=[]
        for col,val in (("status",status),("market_key",market),("model_version",model_version)):
            if val: wh.append(col+"=?"); args.append(val)
        if date_from: wh.append("created_at>=?"); args.append(date_from)
        if date_to: wh.append("created_at<=?"); args.append(date_to+"T23:59:59")
        if query: wh.append("(match_title LIKE ? OR selection LIKE ?)"); args.extend(["%"+query+"%","%"+query+"%"])
        where=(" WHERE "+" AND ".join(wh)) if wh else ""
        with self.connect() as c:
            total=c.execute("SELECT COUNT(*) FROM predictions"+where,args).fetchone()[0]
            rows=[dict(x) for x in c.execute("SELECT * FROM predictions"+where+" ORDER BY id DESC LIMIT ? OFFSET ?",args+[min(int(limit),500),max(int(offset),0)]).fetchall()]
        return {"total":total,"items":rows,"limit":min(int(limit),500),"offset":max(int(offset),0)}

    def model_comparison(self):
        with self.connect() as c:
            rows=[dict(x) for x in c.execute("""SELECT model_version,COUNT(*) total,
              SUM(CASE WHEN status IN ('won','lost') THEN 1 ELSE 0 END) settled,
              SUM(CASE WHEN status='won' THEN 1 ELSE 0 END) wins,
              COALESCE(SUM(CASE WHEN status IN ('won','lost') THEN profit_units ELSE 0 END),0) profit
              FROM predictions GROUP BY model_version ORDER BY model_version DESC""").fetchall()]
        for r in rows:
            r["hit_rate"]=round(100*r["wins"]/r["settled"],1) if r["settled"] else None
            r["roi_percent"]=round(100*r["profit"]/r["settled"],1) if r["settled"] else None
            r["profit"]=round(r["profit"],2)
        return rows

    def summary(self, limit=100):
        with self.connect() as c:
            total=c.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
            settled=c.execute("SELECT COUNT(*) FROM predictions WHERE status IN ('won','lost')").fetchone()[0]
            wins=c.execute("SELECT COUNT(*) FROM predictions WHERE status='won'").fetchone()[0]
            profit=c.execute("SELECT COALESCE(SUM(profit_units),0) FROM predictions WHERE status IN ('won','lost')").fetchone()[0]
            recent=[dict(x) for x in c.execute("SELECT * FROM predictions ORDER BY id DESC LIMIT ?",(int(limit),)).fetchall()]
        return {"total_predictions":total,"settled":settled,"wins":wins,"losses":settled-wins,
                "hit_rate":round(100*wins/settled,1) if settled else None,"profit_units":round(profit,2),
                "roi_percent":round(100*profit/settled,1) if settled else None,"recent":recent}
