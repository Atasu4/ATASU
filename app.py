from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
from collections import Counter
import json, re, math

ROOT=Path(__file__).parent; HISTORY_FILE=ROOT/'data'/'history.json'
if not HISTORY_FILE.exists(): raise RuntimeError('data/history.json bulunamadı.')
HISTORY=json.loads(HISTORY_FILE.read_text(encoding='utf-8'))
MARKETS=['h','d','a','u25','o25','btts','nobtts','u35','o35','iyu15','iyo15','g6']
NAMES={'h':'MS 1','d':'MS X','a':'MS 2','u25':'2,5 Alt','o25':'2,5 Üst','btts':'KG Var','nobtts':'KG Yok','u35':'3,5 Alt','o35':'3,5 Üst','iyu15':'İY 1,5 Alt','iyo15':'İY 1,5 Üst','g6':'6+ Gol'}
GROUPS=[('1X2',['h','d','a']),('2,5 Alt/Üst',['u25','o25']),('3,5 Alt/Üst',['u35','o35']),('Karşılıklı Gol',['btts','nobtts']),('İY 1,5 Alt/Üst',['iyu15','iyo15'])]
app=FastAPI(title='ATASU Intelligence',version='4.5.0')
if (ROOT/'static').exists(): app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

def score(v):
 m=re.fullmatch(r'\s*(\d+)\s*-\s*(\d+)\s*',str(v or '')); return (int(m.group(1)),int(m.group(2))) if m else None

def stats(rows):
 z=Counter(); scores=Counter(); n=nh=tg=hg_sum=ag_sum=0
 for r in rows:
  ft=score(r.get('ft'))
  if not ft: continue
  n+=1; h,a=ft; t=h+a; tg+=t; hg_sum+=h; ag_sum+=a; scores[f'{h}-{a}']+=1
  z['home' if h>a else 'draw' if h==a else 'away']+=1
  z['o15' if t>=2 else 'u15']+=1; z['o25' if t>=3 else 'u25']+=1; z['o35' if t>=4 else 'u35']+=1
  z['btts' if h>0 and a>0 else 'nobtts']+=1
  ht=score(r.get('ht'))
  if ht:
   nh+=1; hh,ha=ht; z['htHome' if hh>ha else 'htDraw' if hh==ha else 'htAway']+=1
   fh=hh+ha; sh=t-fh; z['fh' if fh>sh else 'sh' if sh>fh else 'eq']+=1
 def p(k,d): return round(100*z[k]/d,1) if d else None
 return {'sample_ft':n,'sample_ht':nh,'avg_goals':round(tg/n,2) if n else None,'avg_home_goals':round(hg_sum/n,2) if n else None,'avg_away_goals':round(ag_sum/n,2) if n else None,
 'top_scores':[{'score':s,'count':c,'percent':round(c/n*100,1)} for s,c in scores.most_common(6)] if n else [],
 'MS 1':p('home',n),'MS X':p('draw',n),'MS 2':p('away',n),'1,5 Üst':p('o15',n),'1,5 Alt':p('u15',n),'2,5 Üst':p('o25',n),'2,5 Alt':p('u25',n),'KG Var':p('btts',n),'KG Yok':p('nobtts',n),'3,5 Üst':p('o35',n),'3,5 Alt':p('u35',n),'İY 1':p('htHome',nh),'İY X':p('htDraw',nh),'İY 2':p('htAway',nh),'Daha çok gol 1.Y':p('fh',nh),'Daha çok gol 2.Y':p('sh',nh),'Yarılar eşit':p('eq',nh)}

def probability_engine(q):
 groups=[]
 for title,keys in GROUPS:
  if not all(k in q for k in keys): continue
  inv=[1/q[k] for k in keys]; book=sum(inv)
  # A complete bookmaker market should not have a negative overround. If it does,
  # the pasted values are likely stale/mixed/misparsed. Do not manufacture a fair distribution.
  if book < 1:
   groups.append({'market':title,'book_percent':round(book*100,2),'margin_percent':round((book-1)*100,2),'valid':False,'warning':'Tutarsız tam market: toplam implied probability %100 altında. Marjsız olasılık üretilmedi.','selections':[{'key':k,'name':NAMES[k],'odds':q[k],'raw_percent':round(100/q[k],2),'fair_percent':None} for k in keys]})
   continue
  fair=[x/book for x in inv]
  groups.append({'market':title,'book_percent':round(book*100,2),'margin_percent':round((book-1)*100,2),'valid':True,'warning':None,'selections':[{'key':k,'name':NAMES[k],'odds':q[k],'raw_percent':round(100/q[k],2),'fair_percent':round(100*f,2)} for k,f in zip(keys,fair)]})
 return groups

def match_rows(q,tol,league=''):
 pool=[r for r in HISTORY if score(r.get('ft')) is not None]
 if league.strip(): pool=[r for r in pool if league.strip().casefold() in str(r.get('league','')).casefold()]
 out=[]
 for r in pool:
  diffs={}; compared=matched=0
  for k,target in q.items():
   v=r.get(k)
   if v is None: continue
   try: v=float(v)
   except: continue
   compared+=1; d=abs(v-target); diffs[k]=round(d,3); matched+= d<=tol
  if compared<2: continue
  x=dict(r); x['_matched_odds']=matched; x['_compared_odds']=compared; x['_match_ratio']=round(100*matched/compared,1); x['_differences']=diffs; x['_total_difference']=round(sum(diffs.values()),3); out.append(x)
 searched=len(q); minimum=max(2,(searched+1)//2)
 matches=[x for x in out if x['_matched_odds']>=minimum]
 # Strict mode: if the requested tolerance has no qualifying historical match,
 # return zero. Never promote out-of-tolerance rows into the result set.
 matches.sort(key=lambda x:(-x['_matched_odds'],-x['_match_ratio'],x['_total_difference']))
 return pool,matches,minimum,False

def key_result(k,ft,ht):
 h,a=ft; t=h+a
 return {'h':h>a,'d':h==a,'a':h<a,'o25':t>=3,'u25':t<=2,'o35':t>=4,'u35':t<=3,'btts':h>0 and a>0,'nobtts':h==0 or a==0,'g6':t>=6}.get(k)

def relationship_engine(rows):
 # Derived only from real FT results in the matched historical sample.
 valid=[]
 for r in rows:
  ft=score(r.get('ft'))
  if ft: valid.append(ft)
 n=len(valid)
 if not n: return []
 tests=[
  ('2,5 Üst + KG Var', lambda h,a: h+a>=3 and h>0 and a>0),
  ('2,5 Alt + KG Yok', lambda h,a: h+a<=2 and (h==0 or a==0)),
  ('3,5 Üst + KG Var', lambda h,a: h+a>=4 and h>0 and a>0),
  ('MS 1 + 1,5 Üst', lambda h,a: h>a and h+a>=2),
  ('MS 2 + 1,5 Üst', lambda h,a: h<a and h+a>=2),
  ('Beraberlik + KG Var', lambda h,a: h==a and h>0 and a>0),
 ]
 out=[]
 for name,fn in tests:
  c=sum(1 for h,a in valid if fn(h,a))
  out.append({'name':name,'count':c,'sample':n,'percent':round(100*c/n,1)})
 return sorted(out,key=lambda x:x['percent'],reverse=True)

def market_comparison(stats_obj, prob_groups):
 # Compare historical outcome frequency with de-margined market probability only when both exist.
 hist_map={'h':'MS 1','d':'MS X','a':'MS 2','u25':'2,5 Alt','o25':'2,5 Üst','u35':'3,5 Alt','o35':'3,5 Üst','btts':'KG Var','nobtts':'KG Yok'}
 out=[]
 for g in prob_groups:
  for sel in g.get('selections',[]):
   hk=hist_map.get(sel.get('key'))
   hv=stats_obj.get(hk) if hk else None
   fv=sel.get('fair_percent')
   if not isinstance(hv,(int,float)) or not isinstance(fv,(int,float)): continue
   out.append({'market':g.get('market'),'selection':sel.get('name'),'historical_percent':round(hv,1),'fair_percent':round(fv,2),'difference_points':round(hv-fv,2)})
 return sorted(out,key=lambda x:abs(x['difference_points']),reverse=True)

def insights(s,prob,matched):
 vals=[(k,v) for k,v in s.items() if k not in {'sample_ft','sample_ht','avg_goals','avg_home_goals','avg_away_goals','top_scores'} and isinstance(v,(int,float))]
 vals.sort(key=lambda x:x[1],reverse=True)
 why=[]
 if matched: why.append(f'{matched} gerçek geçmiş maç mevcut filtreleri karşıladı.')
 if vals: why.append(f'Geçmiş sonuçlarda en yüksek oran {vals[0][0]}: %{vals[0][1]:.1f}.')
 if prob: why.append(f'{len(prob)} tam piyasa grubunda bookmaker marjı temizlenebildi.')
 if not prob: why.append('Tam karşıt oran grubu olmadığı için marjsız piyasa olasılığı üretilmedi.')
 return why


# BANKO v1: thresholds are fixed from chronological 60/20/20 backtest on this history dataset.
BANKO_RULES=[
 {'id':'u35','selection':'3,5 Alt','target':'u35','requirements':[('u35','fair',80.0)],'backtest':[(40,34),(35,30),(36,29)]},
 {'id':'iyu15','selection':'İY 1,5 Alt','target':'iyu15','requirements':[('iyu15','fair',70.0),('u35','fair',50.0),('nobtts','fair',55.0)],'backtest':[(66,56),(46,35),(33,26)]},
 {'id':'h','selection':'MS 1','target':'h','requirements':[('h','fair',50.0),('o25','fair',55.0),('nobtts','fair',50.0)],'backtest':[(165,128),(49,39),(38,30)]},
]

def fair_map(prob_groups):
 out={}
 for g in prob_groups:
  if not g.get('valid'): continue
  for x in g.get('selections',[]):
   if isinstance(x.get('fair_percent'),(int,float)): out[x['key']]=float(x['fair_percent'])
 return out

def banko_engine(prob_groups):
 fm=fair_map(prob_groups); candidates=[]
 for rule in BANKO_RULES:
  checks=[]; ok=True
  for key,_,threshold in rule['requirements']:
   actual=fm.get(key); passed=actual is not None and actual>=threshold
   if not passed: ok=False
   checks.append({'market':NAMES.get(key,key),'fair_percent':actual,'minimum_percent':threshold,'passed':passed})
  if not ok: continue
  total=sum(n for n,w in rule['backtest']); wins=sum(w for n,w in rule['backtest'])
  folds=[round(100*w/n,1) for n,w in rule['backtest']]
  candidates.append({'id':rule['id'],'selection':rule['selection'],'sample':total,'wins':wins,'losses':total-wins,'hit_percent':round(100*wins/total,1),'folds':folds,'minimum_fold_percent':min(folds),'checks':checks})
 candidates.sort(key=lambda x:(x['minimum_fold_percent'],x['sample']),reverse=True)
 return {'status':'BANKO ADAYI' if candidates else 'BANKO YOK','candidates':candidates,'note':'Banko garanti değildir. Yalnızca sabit kuralları karşılayan ve kronolojik geçmiş testte doğrulanmış adayları gösterir.'}

class OddsReq(BaseModel):
 odds:dict[str,float|None]; tolerance:float=Field(0.05,ge=0,le=5); league:str=''; limit:int=Field(500,ge=1,le=5000)

@app.get('/')
def root(): return FileResponse(ROOT/'index.html')
@app.get('/api/meta')
def meta():
 return {'history_rows':len(HISTORY),'completed_rows':sum(score(x.get('ft')) is not None for x in HISTORY),'markets':MARKETS,'version':'4.5.0','rule':'Yalnızca history.json içindeki gerçek oran ve sonuçlar kullanılır. Türetilmiş olasılıklar açıkça matematiksel olarak etiketlenir.'}

@app.post('/api/odds')
def odds_scan(req:OddsReq):
 q={}
 for k,v in req.odds.items():
  if k not in MARKETS or v is None: continue
  try: f=float(v)
  except: continue
  if f>1: q[k]=f
 if len(q)<2: raise HTTPException(400,'En az 2 desteklenen gerçek oran bulunmalı.')
 pool,matches,minimum,fallback=match_rows(q,req.tolerance,req.league)
 s=stats(matches); prob=probability_engine(q); banko=banko_engine(prob); relationships=relationship_engine(matches); comparison=market_comparison(s,prob)
 # tolerance sensitivity: same exact query, no invented data
 sensitivity=[]
 for t in sorted(set([max(0.01,round(req.tolerance/2,3)),round(req.tolerance,3),round(req.tolerance*2,3)])):
  _,mm,_,_=match_rows(q,t,req.league); sensitivity.append({'tolerance':t,'matched':len(mm)})
 # funnel: EXACTLY the same matching rule as match_rows; never a separate sequential filter
 # A row is eligible only if at least two queried historical odds exist. Then we show
 # cumulative matched-odds thresholds up to the same minimum used by the result set.
 eligible=[]
 for r in pool:
  compared=0; matched_count=0
  for k,target in q.items():
   try: v=float(r.get(k))
   except: continue
   compared+=1
   if abs(v-target)<=req.tolerance: matched_count+=1
  if compared>=2: eligible.append((r,matched_count,compared))
 funnel=[{'step':'Sonuçlu geçmiş maç','count':len(pool)},
         {'step':'En az 2 karşılaştırılabilir oran','count':len(eligible)}]
 for threshold in range(1, minimum+1):
  funnel.append({'step':f'En az {threshold}/{len(q)} oran ±{req.tolerance} eşleşti',
                 'count':sum(1 for _,m,_ in eligible if m>=threshold)})
 # Strict mode: the final funnel count is the returned match population.
 # inverse examples for strongest historical outcome among supported result keys
 outcome_map={'MS 1':'h','MS X':'d','MS 2':'a','2,5 Üst':'o25','2,5 Alt':'u25','KG Var':'btts','KG Yok':'nobtts','3,5 Üst':'o35','3,5 Alt':'u35'}
 candidates=[(name,s.get(name)) for name in outcome_map if isinstance(s.get(name),(int,float))]
 strongest=max(candidates,key=lambda x:x[1]) if candidates else None
 losses=[]
 if strongest:
  kk=outcome_map[strongest[0]]
  for r in matches:
   ft=score(r.get('ft')); ht=score(r.get('ht'))
   if ft and key_result(kk,ft,ht) is False:
    item={k:r.get(k) for k in ['date','league','home','away','ht','ft']}
    item.update({'_matched_odds':r.get('_matched_odds'),'_compared_odds':r.get('_compared_odds'),'_match_ratio':r.get('_match_ratio'),'_differences':r.get('_differences',{})})
    losses.append(item)
 # League/date breakdown of the exact same matched sample; descriptive only.
 league_counts={}
 date_counts={}
 for r in matches:
  lg=str(r.get('league') or 'Bilinmiyor').strip() or 'Bilinmiyor'
  dt=str(r.get('date') or 'Bilinmiyor').strip() or 'Bilinmiyor'
  league_counts[lg]=league_counts.get(lg,0)+1
  ym=dt[:7] if len(dt)>=7 and dt[4:5]=='-' else dt
  date_counts[ym]=date_counts.get(ym,0)+1
 breakdown={
  'leagues':[{'name':k,'count':v,'percent':round(100*v/len(matches),1)} for k,v in sorted(league_counts.items(),key=lambda x:(-x[1],x[0]))[:12]] if matches else [],
  'periods':[{'name':k,'count':v,'percent':round(100*v/len(matches),1)} for k,v in sorted(date_counts.items(),key=lambda x:x[0],reverse=True)[:12]] if matches else [],
  'sample':len(matches)
 }
 sample_audit={
  'matched_sample':len(matches),
  'completed_pool':len(pool),
  'coverage_percent':round(100*len(matches)/len(pool),2) if pool else 0,
  'warning':'Örneklem 30 maçın altında; yüzdeleri tek başına güçlü kanıt olarak yorumlama.' if len(matches)<30 else None,
  'source':'history.json içindeki sonuçlu gerçek geçmiş maçlar'
 }
 return {'method':f'{len(q)} gerçek oran tarandı. En az {minimum}/{len(q)} oran ±{req.tolerance} içinde eşleşti.','sample_audit':sample_audit,'searched_odds':q,'searched_count':len(q),'tolerance':req.tolerance,'pool_size':len(pool),'matched':len(matches),'returned':min(len(matches),req.limit),'minimum_match_count':minimum,'best_match_count':matches[0]['_matched_odds'] if matches else 0,'stats':s,'probability_engine':prob,'banko':banko,'market_comparison':comparison,'relationships':relationships,'breakdown':breakdown,'sensitivity':sensitivity,'funnel':funnel,'strongest_history':{'market':strongest[0],'percent':strongest[1]} if strongest else None,'counterexamples':losses[:12],'why':insights(s,prob,len(matches)),'matches':matches[:req.limit]}



EXACT_CATEGORIES={
 'MS':['h','d','a'],
 'ALT / ÜST':['u25','o25','u35','o35','g6'],
 'KG':['btts','nobtts'],
 'İY':['iyu15','iyo15'],
 'KORNER':[]
}

def exact_equal(a,b):
 try: return float(a)==float(b)
 except: return False

def exact_rows(q, keys):
 active=[k for k in keys if k in q]
 if not active: return [],active
 rows=[]
 for r in HISTORY:
  if score(r.get('ft')) is None: continue
  if all(r.get(k) is not None and exact_equal(r.get(k),q[k]) for k in active): rows.append(r)
 return rows,active

def exact_summary(rows, category=None):
 s=stats(rows); n=s.get('sample_ft',0)
 bycat={
  'MS':['MS 1','MS X','MS 2'],
  'ALT / ÜST':['1,5 Üst','1,5 Alt','2,5 Üst','2,5 Alt','3,5 Üst','3,5 Alt'],
  'KG':['KG Var','KG Yok'],
  'İY':['İY 1','İY X','İY 2'],
 }
 labels=bycat.get(category,['MS 1','MS X','MS 2','1,5 Üst','1,5 Alt','2,5 Üst','2,5 Alt','3,5 Üst','3,5 Alt','KG Var','KG Yok','İY 1','İY X','İY 2'])
 outcomes=[]
 for name in labels:
  v=s.get(name)
  if isinstance(v,(int,float)):
   outcomes.append({'name':name,'percent':v,'count':round(n*v/100) if n else 0})
 outcomes.sort(key=lambda x:(-x['percent'],-x['count'],x['name']))
 return {'sample':n,'outcomes':outcomes,'top':outcomes[:6]}

@app.post('/api/exact-odds')
def exact_odds_scan(req:OddsReq):
 q={}
 for k,v in req.odds.items():
  if k not in MARKETS or v is None: continue
  try: f=float(v)
  except: continue
  if f>1: q[k]=f
 if not q: raise HTTPException(400,'Desteklenen en az 1 gerçek oran bulunmalı.')
 categories=[]
 for name,keys in EXACT_CATEGORIES.items():
  if name=='KORNER':
   categories.append({'category':name,'status':'VERİ YOK','used_odds':{},'matched':0,'summary':{'sample':0,'outcomes':[],'top':[]},'matches':[],'note':'history.json içinde korner oran sütunu bulunmuyor.'})
   continue
  rows,active=exact_rows(q,keys)
  if not active:
   categories.append({'category':name,'status':'ORAN GİRİLMEDİ','used_odds':{},'matched':0,'summary':{'sample':0,'outcomes':[],'top':[]},'matches':[]})
   continue
  categories.append({'category':name,'status':'EŞLEŞME VAR' if rows else 'BİREBİR EŞLEŞME YOK','used_odds':{k:q[k] for k in active},'matched':len(rows),'summary':exact_summary(rows,name),'matches':[{k:r.get(k) for k in ['date','league','home','away','ht','ft']} for r in rows[:200]]})
 allkeys=list(q)
 combined,_=exact_rows(q,allkeys)
 return {'method':'TOLERANS YOK — yalnızca girilen oranlarla sayısal olarak birebir aynı geçmiş kayıtlar kullanılır.','searched_odds':q,'categories':categories,'combined':{'matched':len(combined),'used_odds':q,'summary':exact_summary(combined),'matches':[{k:r.get(k) for k in ['date','league','home','away','ht','ft']} for r in combined[:300]]},'corner_available':False,'source_rows':len(HISTORY),'completed_rows':sum(score(x.get('ft')) is not None for x in HISTORY)}

class Plus6Req(BaseModel): o25:float|None=None; o35:float|None=None; o45:float|None=None; btts:float|None=None; iy05:float|None=None; nofirst:float|None=None
@app.post('/api/plus6')
def plus6(q:Plus6Req):
 rules=[('2,5 Üst',q.o25,1.20,1.28),('3,5 Üst',q.o35,1.66,1.89),('4,5 Üst',q.o45,2.64,3.14),('KG Var',q.btts,1.22,1.87)]
 output=[]; hit=0
 for name,v,lo,hi in rules:
  m=v is not None and lo<=v<=hi; hit+=m; output.append({'name':name,'value':v,'range':[lo,hi],'match':m})
 last=(q.iy05 is not None and 1.05<=q.iy05<=1.08) or (q.nofirst is not None and 22.10<=q.nofirst<=26.00); hit+=last
 output.append({'name':'İY 0,5 Üst veya İlk Gol Olmaz','values':[q.iy05,q.nofirst],'ranges':[[1.05,1.08],[22.10,26.00]],'match':last})
 return {'matched_rules':hit,'total_rules':5,'compatibility_percent':round(hit/5*100),'rules':output,'note':'Yalnızca kayıtlı +6 referans bantlarıyla karşılaştırmadır.'}
