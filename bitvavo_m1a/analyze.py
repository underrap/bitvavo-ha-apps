#!/usr/bin/env python3
"""M1A same-venue microstructure information test. Research only; no trading."""
import argparse,bisect,hashlib,heapq,json,math,random,statistics
from array import array
from collections import Counter,deque
from pathlib import Path
VERSION='1.2.0';PROTOCOL='M1A-PREREG-v1.3';CONTENT_PROTOCOL='M1A-PREREG-v1.2';MARKETS=('BTC-EUR','BTC-USDC');PRIMARY='BTC-EUR'
GRID_NS=500_000_000;LOOKBACK_NS=1_000_000_000
HORIZONS_NS=(500_000_000,1_000_000_000,2_000_000_000,5_000_000_000)
BLOCK_NS=60_000_000_000;BOOTSTRAPS=10000;SEED=20261002

class Series:
 def __init__(self):
  self.t=array('q');self.valid=bytearray();self.nonce=array('q');self.bid=array('d');self.ask=array('d');self.f1=array('d');self.f2=array('d');self.f3=array('d');self.book_version=array('q');self.epoch=array('q')
 def add(self,t,valid,nonce,bid,ask,f1,f2,f3,version,epoch):
  self.t.append(t);self.valid.append(1 if valid else 0);self.nonce.append(nonce if nonce is not None else -1)
  for a,v in ((self.bid,bid),(self.ask,ask),(self.f1,f1),(self.f2,f2),(self.f3,f3)):a.append(v if v is not None else math.nan)
  self.book_version.append(version);self.epoch.append(epoch)
 def __len__(self):return len(self.t)

def clean(x):
 if isinstance(x,float) and not math.isfinite(x):return None
 if isinstance(x,dict):return {k:clean(v) for k,v in x.items()}
 if isinstance(x,(list,tuple)):return [clean(v) for v in x]
 return x

def qtile(xs,p):
 ys=sorted(x for x in xs if math.isfinite(x))
 if not ys:return math.nan
 pos=(len(ys)-1)*p;lo=int(pos);hi=min(len(ys)-1,lo+1);w=pos-lo
 return ys[lo]*(1-w)+ys[hi]*w

def stats(xs):
 a=[x for x in xs if math.isfinite(x)]
 if not a:return {'n':0}
 return {'n':len(a),'mean':statistics.fmean(a),'median':statistics.median(a),'p05':qtile(a,.05),'p25':qtile(a,.25),'p75':qtile(a,.75),'p95':qtile(a,.95),'p_positive':sum(x>0 for x in a)/len(a),'p_negative':sum(x<0 for x in a)/len(a)}

def imbalance(b,a):
 d=b+a;return (b-a)/d if d>0 else math.nan

def book_metrics(bids,asks):
 if not bids or not asks:return None
 bp=heapq.nlargest(5,((float(p),float(s)) for p,s in bids.items() if float(s)>0),key=lambda x:x[0])
 ap=heapq.nsmallest(5,((float(p),float(s)) for p,s in asks.items() if float(s)>0),key=lambda x:x[0])
 if not bp or not ap:return None
 bid,bs=bp[0];ask,az=ap[0]
 return bid,ask,imbalance(bs,az),imbalance(sum(s for _,s in bp),sum(s for _,s in ap))

def apply(book,msg):
 for side in ('bids','asks'):
  d=book[side]
  for p,s in msg.get(side,[]):
   if float(s)==0:d.pop(p,None)
   else:d[p]=s
 book['nonce']=int(msg['nonce'])

def load_jsonl(p):
 with p.open(encoding='utf-8') as f:
  for ln,line in enumerate(f,1):
   try:yield json.loads(line)
   except Exception as e:raise RuntimeError(f'{p}:{ln}: invalid JSON: {e}')

def audit_manifest(root):
 mf=json.loads((root/'freeze_manifest.json').read_text(encoding='utf-8'));errs=[]
 if mf.get('m0_version')!='1.0.5':errs.append(f"m0_version={mf.get('m0_version')!r}; expected '1.0.5'")
 for name in ('raw_events.jsonl','sessions.jsonl','book_checkpoints.jsonl'):
  meta=mf.get('files',{}).get(name);p=root/name
  if not meta or not p.exists():errs.append(f'missing required frozen file/metadata {name}');continue
  h=hashlib.sha256(p.read_bytes()).hexdigest()
  if h!=meta.get('sha256'):errs.append(f'hash mismatch {name}')
 return mf,errs

def build_series(root,market,audit):
 cps=sorted((x for x in load_jsonl(root/'book_checkpoints.jsonl') if x.get('market')==market),key=lambda x:int(x['mono_ns']))
 if not cps:raise RuntimeError(f'No persisted book checkpoint for {market}; M1A F1/F2 impossible on this freeze.')
 last=-1;regress=0
 for r in load_jsonl(root/'raw_events.jsonl'):
  t=int(r['recv_mono_ns'])
  if last>=0 and t<last:regress+=1
  last=t
 audit[market]['monotonic_regressions']=regress
 if regress:raise RuntimeError(f'{market}: monotonic receive clock regressed; split by boot epoch first.')
 invalid_kinds={'connect','disconnect','duplicate_nonce','stale_nonce','forward_nonce_gap','nonce_gap','resync_failed','resync_exception'}
 invalid_times=sorted(int(x['mono_ns']) for x in load_jsonl(root/'sessions.jsonl') if x.get('kind') in invalid_kinds and x.get('market') in (None,market))
 cp_times=[int(x['mono_ns']) for x in cps]
 def interval_valid(t):
  ci=bisect.bisect_right(cp_times,t)-1
  if ci<0:return False
  ii=bisect.bisect_right(invalid_times,t)-1
  return ii<0 or invalid_times[ii]<cp_times[ci]
 cp_i=0;cp=cps[0];book={'bids':dict(cp['bids']),'asks':dict(cp['asks']),'nonce':int(cp['nonce'])}
 valid=True;version=0;first_cp_t=int(cp['mono_ns']);next_cp_t=int(cps[1]['mono_ns']) if len(cps)>1 else None
 trades=deque()
 # Hard segment boundary: TFI may not look back across a checkpoint/reconnect boundary.
 zero_trade=repeated=0;last_ver=None;s=Series();next_grid=((first_cp_t+GRID_NS-1)//GRID_NS)*GRID_NS
 crossed=neg_size=bad_price=nonce_anom=invalid_grids=0
 events=(r for r in load_jsonl(root/'raw_events.jsonl') if r.get('raw',{}).get('market')==market and int(r['recv_mono_ns'])>=first_cp_t)
 try:current=next(events)
 except StopIteration:current=None
 while current is not None or next_cp_t is not None:
  event_t=int(current['recv_mono_ns']) if current is not None else 2**63-1
  boundary=min(event_t,next_cp_t if next_cp_t is not None else 2**63-1)
  while next_grid<boundary:
   while trades and trades[0][0]<next_grid-LOOKBACK_NS:trades.popleft()
   buy=sum(v for t,side,v in trades if t<=next_grid and side=='buy');sell=sum(v for t,side,v in trades if t<=next_grid and side=='sell')
   f3=imbalance(buy,sell) if buy+sell>0 else 0.0
   if buy+sell==0:zero_trade+=1
   met=book_metrics(book['bids'],book['asks']) if valid and interval_valid(next_grid) else None
   if met:
    bid,ask,f1,f2=met;valid_now=bid<ask and bid>0 and ask>0
    if bid>=ask:crossed+=1
    if bid<=0 or ask<=0:bad_price+=1
   else:bid=ask=f1=f2=math.nan;valid_now=False
   if not valid_now:invalid_grids+=1
   if last_ver==version:repeated+=1
   last_ver=version;s.add(next_grid,valid_now,book.get('nonce'),bid,ask,f1,f2,f3,version,cp_i);next_grid+=GRID_NS
  if next_cp_t is not None and next_cp_t<=event_t:
   cp_i+=1;cp=cps[cp_i];book={'bids':dict(cp['bids']),'asks':dict(cp['asks']),'nonce':int(cp['nonce'])};valid=True;version+=1
   next_cp_t=int(cps[cp_i+1]['mono_ns']) if cp_i+1<len(cps) else None;continue
  if current is None:break
  msg=current['raw']
  if msg.get('event')=='trade':
   try:trades.append((event_t,msg['side'],float(msg['amount'])))
   except Exception:audit[market]['malformed_trades']+=1
  elif msg.get('event')=='book':
   n=int(msg['nonce']);expected=int(book['nonce'])+1
   if valid and n==expected:
    for side in ('bids','asks'):
     for p,z in msg.get(side,[]):
      if float(p)<=0:bad_price+=1
      if float(z)<0:neg_size+=1
    apply(book,msg);version+=1
   elif valid and n!=expected:nonce_anom+=1;valid=False
  try:current=next(events)
  except StopIteration:current=None
 audit[market].update({'crossed_grids':crossed,'negative_size_updates':neg_size,'nonpositive_price_updates':bad_price,'nonce_anomalies_replay':nonce_anom,'invalid_grids':invalid_grids,'valid_grids':len(s)-invalid_grids,'valid_analysis_seconds':(len(s)-invalid_grids)*0.5,'grid_points':len(s),'same_bookstate_consecutive_grids':repeated,'same_bookstate_fraction':repeated/len(s) if len(s) else None,'zero_tradeflow_grids':zero_trade,'zero_tradeflow_fraction':zero_trade/len(s) if len(s) else None,'first_checkpoint_mono_ns':first_cp_t,'checkpoint_count':len(cps)})
 return s

def rankdata(xs):
 order=sorted(range(len(xs)),key=xs.__getitem__);out=[0.0]*len(xs);i=0
 while i<len(order):
  j=i+1;v=xs[order[i]]
  while j<len(order) and xs[order[j]]==v:j+=1
  r=(i+1+j)/2
  for k in range(i,j):out[order[k]]=r
  i=j
 return out

def pearson(x,y):
 if len(x)<2 or len(x)!=len(y):return math.nan
 mx=statistics.fmean(x);my=statistics.fmean(y);sx=sy=sxy=0.0
 for a,b in zip(x,y):
  da=a-mx;db=b-my;sx+=da*da;sy+=db*db;sxy+=da*db
 return sxy/math.sqrt(sx*sy) if sx>0 and sy>0 else math.nan

def spearman(x,y):
 rows=[(float(a),float(b)) for a,b in zip(x,y) if math.isfinite(float(a)) and math.isfinite(float(b))]
 if len(rows)<2:return math.nan
 xx=[z[0] for z in rows];yy=[z[1] for z in rows]
 return pearson(rankdata(xx),rankdata(yy))

def describe(xs):
 a=[float(x) for x in xs if math.isfinite(float(x))]
 if not a:return {'n':0,'mean':None,'median':None,'std':None}
 return {'n':len(a),'mean':statistics.fmean(a),'median':statistics.median(a),'std':statistics.stdev(a) if len(a)>1 else 0.0}

def feature_arr(s,name):
 return {'L1':s.f1,'D5':s.f2,'TFI_1s':s.f3}[name]

def target_bps(s,i,h):
 step=h//GRID_NS;j=i+step
 if j>=len(s):return None
 if s.t[j]!=s.t[i]+h or not s.valid[i] or not s.valid[j] or s.epoch[i]!=s.epoch[j]:return None
 if any(not s.valid[k] for k in range(i,j+1)):return None
 m0=(s.bid[i]+s.ask[i])/2;m1=(s.bid[j]+s.ask[j])/2
 return 10000*(m1/m0-1)

def primary_eligible(s):
 out=[]
 for i in range(len(s)):
  if not s.valid[i] or not math.isfinite(s.f1[i]):continue
  if target_bps(s,i,1_000_000_000) is not None:out.append(i)
 return out

def split_primary(s):
 ids=primary_eligible(s);ids.sort(key=lambda i:s.t[i]);nd=math.floor(.60*len(ids))
 d=ids[:nd];h=ids[nd:];boundary=s.t[h[0]] if h else math.inf
 return d,h,boundary

def rows_for(s,feature,h,part,boundary):
 arr=feature_arr(s,feature);rows=[]
 for i in range(len(s)):
  if part=='DISCOVERY' and s.t[i]>=boundary:continue
  if part=='HOLDOUT' and s.t[i]<boundary:continue
  if not s.valid[i] or not math.isfinite(arr[i]):continue
  y=target_bps(s,i,h)
  if y is None or not math.isfinite(y):continue
  rows.append((int(s.t[i]),int(s.epoch[i]),float(arr[i]),float(y),i))
 return rows

def elapsed_seconds(rows):
 by={}
 for t,e,*_ in rows:
  z=by.setdefault(e,[t,t]);z[0]=min(z[0],t);z[1]=max(z[1],t)
 return sum((b-a+GRID_NS)/1e9 for a,b in by.values())

def nonoverlap_blocks(rows):
 by={}
 for t,e,*_ in rows:by.setdefault(e,[]).append(t)
 n=0
 for ts in by.values():
  ts.sort()
  if not ts:continue
  start=ts[0];last=ts[-1]
  while start+BLOCK_NS<=last+GRID_NS:
   lo=bisect.bisect_left(ts,start);hi=bisect.bisect_left(ts,start+BLOCK_NS)
   if hi-lo>=2:n+=1
   start+=BLOCK_NS
 return n

def moving_blocks(rows):
 by={}
 for p,r in enumerate(rows):by.setdefault(r[1],[]).append(p)
 out=[]
 for pos in by.values():
  times=[rows[p][0] for p in pos]
  for a,p in enumerate(pos):
   t0=rows[p][0];hi=bisect.bisect_left(times,t0+BLOCK_NS,lo=a)
   if hi<len(times) and times[hi]>=t0+BLOCK_NS:
    block=pos[a:hi]
    if len(block)>=2:out.append(block)
 return out

def bootstrap_primary(rows):
 obs=spearman([r[2] for r in rows],[r[3] for r in rows]);blocks=moving_blocks(rows)
 if not math.isfinite(obs) or not blocks:return {'rho':clean(obs),'replicates':0,'p_boot':None,'ci95':[None,None],'moving_block_candidates':len(blocks)}
 rng=random.Random(SEED);sims=[];n=len(rows)
 for _ in range(BOOTSTRAPS):
  pick=[]
  while len(pick)<n:pick.extend(blocks[rng.randrange(len(blocks))])
  pick=pick[:n];rho=spearman([rows[p][2] for p in pick],[rows[p][3] for p in pick])
  if math.isfinite(rho):sims.append(rho)
 if len(sims)!=BOOTSTRAPS:return {'rho':obs,'replicates':len(sims),'p_boot':None,'ci95':[None,None],'moving_block_candidates':len(blocks)}
 return {'rho':obs,'replicates':len(sims),'p_boot':(1+sum(x<=0 for x in sims))/(BOOTSTRAPS+1),'ci95':[qtile(sims,.025),qtile(sims,.975)],'moving_block_candidates':len(blocks)}

def quarter_rows(rows):
 q,r=divmod(len(rows),4);out=[];at=0
 for k in range(4):
  n=q+(1 if k<r else 0);out.append(rows[at:at+n]);at+=n
 return out

def contrast(rows,q20,q80):
 lo=[r[3] for r in rows if r[2]<=q20];hi=[r[3] for r in rows if r[2]>=q80]
 return {'value_bps':statistics.fmean(hi)-statistics.fmean(lo) if lo and hi else None,'low_n':len(lo),'high_n':len(hi)}

def trim_primary(rows):
 ys=[r[3] for r in rows]
 if not ys:return {'q01_bps':None,'q99_bps':None,'n':0,'rho':None}
 q01=qtile(ys,.01);q99=qtile(ys,.99);keep=[r for r in rows if q01<=r[3]<=q99]
 return {'q01_bps':q01,'q99_bps':q99,'n':len(keep),'rho':clean(spearman([r[2] for r in keep],[r[3] for r in keep]))}

def feature_quantiles(s,dids):
 out={}
 for f in ('L1','D5','TFI_1s'):
  arr=feature_arr(s,f);vals=[arr[i] for i in dids if math.isfinite(arr[i])]
  out[f]={'q20':clean(qtile(vals,.20)),'q80':clean(qtile(vals,.80)),'n':len(vals)}
 return out

def matrix(s,dids,hids,boundary):
 qs=feature_quantiles(s,dids);out={}
 for f in ('L1','D5','TFI_1s'):
  out[f]={'discovery_quantiles':qs[f],'horizons':{}}
  for h in HORIZONS_NS:
   hk=f'{h/1e9:g}s';d=rows_for(s,f,h,'DISCOVERY',boundary);ho=rows_for(s,f,h,'HOLDOUT',boundary)
   out[f]['horizons'][hk]={
    'DISCOVERY':{'n':len(d),'feature':describe(r[2] for r in d),'target_bps':describe(r[3] for r in d),'spearman_rho':clean(spearman([r[2] for r in d],[r[3] for r in d]))},
    'HOLDOUT':{'n':len(ho),'feature':describe(r[2] for r in ho),'target_bps':describe(r[3] for r in ho),'spearman_rho':clean(spearman([r[2] for r in ho],[r[3] for r in ho]))}
   }
 return out,qs

def evaluate_primary(s,dids,hids,boundary,q):
 rows=rows_for(s,'L1',1_000_000_000,'HOLDOUT',boundary);expected=set(hids);actual={r[4] for r in rows}
 c=contrast(rows,q['q20'],q['q80']) if q.get('q20') is not None and q.get('q80') is not None else {'value_bps':None,'low_n':0,'high_n':0}
 quarters=quarter_rows(rows);qr=[clean(spearman([r[2] for r in z],[r[3] for r in z])) for z in quarters];tr=trim_primary(rows)
 checks={
  'primary_population_match':expected==actual,
  'primary_eligible_total_at_least_3600':len(dids)+len(hids)>=3600,
  'holdout_primary_eligible_at_least_1440':len(rows)>=1440,
  'holdout_valid_seconds_at_least_1800':elapsed_seconds(rows)>=1800,
  'at_least_10_valid_60s_blocks':nonoverlap_blocks(rows)>=10,
  'all_four_quarters_nonempty':all(len(z)>=1 for z in quarters),
  'q20_holdout_group_at_least_30':c['low_n']>=30,
  'q80_holdout_group_at_least_30':c['high_n']>=30,
  'trim_leaves_at_least_1000':tr['n']>=1000
 }
 structural=all(checks.values())
 boot=bootstrap_primary(rows) if structural else {'rho':clean(spearman([r[2] for r in rows],[r[3] for r in rows])),'replicates':0,'p_boot':None,'ci95':[None,None],'moving_block_candidates':len(moving_blocks(rows))}
 numerical=boot['rho'] is not None and boot['replicates']==BOOTSTRAPS and boot['p_boot'] is not None and boot['ci95'][0] is not None and c['value_bps'] is not None
 checks['confirmatory_statistics_numerically_defined']=numerical
 if not all(checks.values()):
  decision='INCONCLUSIVE';conds=None;failed=[k for k,v in checks.items() if not v]
 else:
  conds={'rho_gt_0':boot['rho']>0,'p_boot_lt_0_05':boot['p_boot']<.05,'ci95_lower_gt_0':boot['ci95'][0]>0,'q80_minus_q20_gt_0':c['value_bps']>0,'at_least_3_of_4_quarter_rhos_gt_0':sum(x is not None and x>0 for x in qr)>=3,'trimmed_rho_gt_0':tr['rho'] is not None and tr['rho']>0}
  decision='PASS' if all(conds.values()) else 'FAIL';failed=[k for k,v in conds.items() if not v]
 return {'population_n':len(rows),'valid_chronological_seconds':elapsed_seconds(rows),'distinct_valid_60s_blocks':nonoverlap_blocks(rows),'bootstrap':boot,'q80_minus_q20':c,'quarter_rhos':qr,'trim':tr,'minimum_data_checks':checks,'pass_conditions':conds,'failed_conditions':failed,'decision':decision}

def render_report(r):
 p=r['primary_confirmatory'];lines=['# M1A Research Report','',f'- Protocol: {r["protocol"]}',f'- Executor: {r["executor_version"]}',f'- Freeze cutoff: {r["freeze_manifest"].get("research_cutoff_utc")}',f'- Decision: **{p["decision"]}**','','## Primary confirmatory gate',f'- HOLDOUT N: {p["population_n"]}',f'- Spearman rho: {p["bootstrap"]["rho"]}',f'- one-sided bootstrap p: {p["bootstrap"]["p_boot"]}',f'- percentile 95% CI: {p["bootstrap"]["ci95"]}',f'- q80-q20 contrast (bp): {p["q80_minus_q20"]["value_bps"]}',f'- quarter rhos: {p["quarter_rhos"]}',f'- trimmed rho: {p["trim"]["rho"]}','','## Minimum-data / integrity gates']
 for k,v in p['minimum_data_checks'].items():lines.append(f'- {k}: {v}')
 lines+=['','## Audit']
 for m,a in r['audit']['markets'].items():lines.append(f'- {m}: {a}')
 lines+=['','## Interpretation boundary','M1A tests event-level information only. It is not a trading strategy and contains no fee/P&L conclusion.']
 return '\n'.join(lines)+'\n'

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--output',required=True);a=ap.parse_args();root=Path(a.input).resolve();outdir=Path(a.output).resolve();outdir.mkdir(parents=True,exist_ok=True)
 mf,errs=audit_manifest(root)
 if errs:raise SystemExit('Freeze provenance/hash audit failed: '+repr(errs))
 audit={m:Counter() for m in MARKETS};series={}
 try:
  for m in MARKETS:series[m]=build_series(root,m,audit)
 except RuntimeError as e:
  r={'schema':'m1a-results-v1.3','protocol':PROTOCOL,'executor_version':VERSION,'freeze_manifest':mf,'decision':'INCONCLUSIVE','integrity_error':str(e)}
  (outdir/'results.json').write_text(json.dumps(clean(r),indent=2,sort_keys=True)+'\n',encoding='utf-8');(outdir/'report.md').write_text(f'# M1A Research Report\n\n**INCONCLUSIVE** — {e}\n',encoding='utf-8');print(json.dumps({'decision':'INCONCLUSIVE','reason':str(e)},indent=2));return
 d,h,boundary=split_primary(series[PRIMARY]);primary_matrix,qs=matrix(series[PRIMARY],d,h,boundary);primary=evaluate_primary(series[PRIMARY],d,h,boundary,qs['L1'])
 result={'schema':'m1a-results-v1.3','protocol':PROTOCOL,'content_protocol':CONTENT_PROTOCOL,'executor_version':VERSION,'freeze_manifest':mf,'predeclared':{'primary_market':PRIMARY,'exploratory_market':'BTC-USDC','grid_ms':500,'primary_feature':'L1','primary_horizon_ms':1000,'secondary_features':['D5','TFI_1s'],'secondary_horizons_ms':[500,2000,5000],'bootstrap_block_seconds':60,'bootstrap_replicates':BOOTSTRAPS,'seed':SEED},'split':{'primary_eligible_total':len(d)+len(h),'discovery_n':len(d),'holdout_n':len(h),'holdout_boundary_grid_mono_ns':None if boundary==math.inf else boundary},'discovery_feature_quantiles':qs,'audit':{'manifest_errors':[],'markets':{m:dict(audit[m]) for m in MARKETS}},'markets':{PRIMARY:primary_matrix},'primary_confirmatory':primary,'decision':primary['decision']}
 if len(series['BTC-USDC']):
  du,hu,bu=split_primary(series['BTC-USDC']);um,_=matrix(series['BTC-USDC'],du,hu,bu);result['markets']['BTC-USDC']=um;result['exploratory_split']={'discovery_n':len(du),'holdout_n':len(hu)}
 result=clean(result);(outdir/'results.json').write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8');(outdir/'report.md').write_text(render_report(result),encoding='utf-8');print(json.dumps({'decision':result['decision'],'results':str(outdir/'results.json'),'report':str(outdir/'report.md')},indent=2))

if __name__=='__main__':main()
