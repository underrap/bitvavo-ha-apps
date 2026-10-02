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

def bins_for(vals):
 qs=[qtile(vals,p) for p in (.1,.3,.7,.9)];return qs

def block_boot_diff(times,values,groups):
 rows=[(t,v,g) for t,v,g in zip(times,values,groups) if math.isfinite(v) and g in (4,0)]
 if not rows:return {'n':0,'mean_diff':None,'ci95':[None,None]}
 blocks={};t0=rows[0][0]
 for t,v,g in rows:
  d=blocks.setdefault((t-t0)//BLOCK_NS,[0.,0,0.,0])
  if g==4:d[0]+=v;d[1]+=1
  else:d[2]+=v;d[3]+=1
 bs=list(blocks.values())
 def calc(sample):
  st=nt=sb=nb=0
  for d in sample:st+=d[0];nt+=d[1];sb+=d[2];nb+=d[3]
  return st/nt-sb/nb if nt and nb else math.nan
 obs=calc(bs);rng=random.Random(SEED);sims=[]
 if len(bs)>=2:
  for _ in range(BOOTSTRAPS):
   x=calc([bs[rng.randrange(len(bs))] for _ in range(len(bs))])
   if math.isfinite(x):sims.append(x)
 return {'n':len(rows),'blocks':len(bs),'mean_diff':obs,'ci95':[qtile(sims,.025),qtile(sims,.975)] if sims else [None,None]}

def analyze_market(s,market):
 out={'market':market,'grid_points':len(s),'horizons':{},'features':{}};fa={'F1_L1':s.f1,'F2_L5':s.f2,'F3_trade_1s':s.f3};base=[i for i in range(len(s)) if s.valid[i]];defs={}
 for fn,arr in fa.items():
  qs=bins_for(arr[i] for i in base if math.isfinite(arr[i]));defs[fn]=qs;out['features'][fn]={'distribution':stats([arr[i] for i in base if math.isfinite(arr[i])]),'quantiles_10_30_70_90':qs}
 for h in HORIZONS_NS:
  step=h//GRID_NS;hk=f'{h/1e9:g}s';hout={}
  for fn,arr in fa.items():
   qs=defs[fn]
   def grp(v):
    if v<=qs[0]:return 0
    if v<=qs[1]:return 1
    if v<qs[2]:return 2
    if v<qs[3]:return 3
    return 4
   vals=[];groups=[];times=[];execs=[];down=[]
   for i in range(len(s)-step):
    j=i+step
    if not s.valid[i] or not s.valid[j] or s.epoch[i]!=s.epoch[j] or any(not s.valid[k] for k in range(i,j+1)):continue
    v=arr[i]
    if not math.isfinite(v):continue
    mid0=(s.bid[i]+s.ask[i])/2;mid1=(s.bid[j]+s.ask[j])/2
    vals.append(mid1/mid0-1);execs.append(s.bid[j]/s.ask[i]-1);down.append(s.bid[i]/s.ask[j]-1);groups.append(grp(v));times.append(s.t[i])
   gs=[]
   for g in range(5):
    gs.append({'group':g,'future_mid_return':stats([v for v,x in zip(vals,groups) if x==g]),'executable_buy_markout':stats([v for v,x in zip(execs,groups) if x==g]),'downward_sell_then_buy_response':stats([v for v,x in zip(down,groups) if x==g])})
   boot=block_boot_diff(times,vals,groups);top_exec=[v for v,g in zip(execs,groups) if g==4];top_rows=[(t,v) for t,v,g in zip(times,execs,groups) if g==4 and math.isfinite(v)]
   blocks={}
   if top_rows:
    t0=top_rows[0][0]
    for t,v in top_rows:
     d=blocks.setdefault((t-t0)//BLOCK_NS,[0.,0]);d[0]+=v;d[1]+=1
   rng=random.Random(SEED+int(h//GRID_NS));sims=[];bl=list(blocks.values())
   if len(bl)>=2:
    for _ in range(BOOTSTRAPS):
     samp=[bl[rng.randrange(len(bl))] for _ in range(len(bl))];sims.append(sum(x[0] for x in samp)/sum(x[1] for x in samp))
   means=[g['future_mid_return'].get('mean',math.nan) for g in gs];adj=[means[k+1]>=means[k] for k in range(4) if math.isfinite(means[k]) and math.isfinite(means[k+1])]
   boot['mean_diff_bps']=boot['mean_diff']*10000 if boot['mean_diff'] is not None else None
   if boot['ci95'][0] is not None:boot['ci95_bps']=[boot['ci95'][0]*10000,boot['ci95'][1]*10000]
   hout[fn]={'n':len(vals),'potential_grid_points':max(0,len(s)-step),'excluded_invalid_or_resync':max(0,len(s)-step)-len(vals),'groups':gs,'top_minus_bottom_mid_return':boot,'top10_executable_markout':stats(top_exec),'top10_executable_bootstrap_ci95':[qtile(sims,.025),qtile(sims,.975)] if sims else [None,None],'top10_executable_mean_bps':statistics.fmean(top_exec)*10000 if top_exec else None,'monotone_adjacent_fraction':sum(adj)/len(adj) if adj else None}
  out['horizons'][hk]=hout
 return out

def subset_contrast(s,feature,h,selector,trim=None):
 step=h//GRID_NS;arr={'F1_L1':s.f1,'F2_L5':s.f2,'F3_trade_1s':s.f3}[feature]
 idx=[i for i in range(len(s)-step) if selector(i) and s.valid[i] and s.valid[i+step] and s.epoch[i]==s.epoch[i+step] and all(s.valid[k] for k in range(i,i+step+1)) and math.isfinite(arr[i])]
 if not idx:return None
 q10=qtile((arr[i] for i in idx),.1);q90=qtile((arr[i] for i in idx),.9);rows=[]
 for i in idx:rows.append((arr[i],((s.bid[i+step]+s.ask[i+step])/2)/((s.bid[i]+s.ask[i])/2)-1))
 if trim is not None:
  c=qtile((abs(r) for _,r in rows),trim);rows=[x for x in rows if abs(x[1])<=c]
 top=[r for f,r in rows if f>=q90];bot=[r for f,r in rows if f<=q10]
 return statistics.fmean(top)-statistics.fmean(bot) if top and bot else None

def robustness(s):
 n=len(s);mid=n//2;per=Counter();t0=s.t[0] if n else 0
 for i in range(1,n):
  delta=s.book_version[i]-s.book_version[i-1]
  if delta>0:per[(s.t[i]-t0)//BLOCK_NS]+=delta
 med=statistics.median(per.values()) if per else 0;active={k:v>med for k,v in per.items()};out={'active_rule':f'60s book-update count > median ({med})','tests':{}}
 for f in ('F1_L1','F2_L5','F3_trade_1s'):
  out['tests'][f]={}
  for h in HORIZONS_NS:
   hk=f'{h/1e9:g}s';out['tests'][f][hk]={'first_half':subset_contrast(s,f,h,lambda i:i<mid),'second_half':subset_contrast(s,f,h,lambda i:i>=mid),'quiet':subset_contrast(s,f,h,lambda i:not active.get((s.t[i]-t0)//BLOCK_NS,False)),'active':subset_contrast(s,f,h,lambda i:active.get((s.t[i]-t0)//BLOCK_NS,False)),'trim_largest_abs_1pct':subset_contrast(s,f,h,lambda i:True,.99)}
 return out

def classify(primary,rob):
 qualifying=[];executable=[]
 for hk,h in primary['horizons'].items():
  for f,r in h.items():
   b=r['top_minus_bottom_mid_return'];ci=b['ci95'];mono=r['monotone_adjacent_fraction'];rr=rob['tests'][f][hk]
   stable=all(rr[k] is not None and rr[k]>0 for k in ('first_half','second_half','trim_largest_abs_1pct'))
   info=b['mean_diff'] is not None and b['mean_diff']>0 and ci[0] is not None and ci[0]>0 and mono is not None and mono>=.75 and stable
   if info:
    qualifying.append({'feature':f,'horizon':hk,'contrast':b['mean_diff'],'ci95':ci,'monotonicity':mono});eci=r['top10_executable_bootstrap_ci95'];em=r['top10_executable_markout'].get('mean')
    if em is not None and em>0 and eci[0] is not None and eci[0]>0:executable.append({'feature':f,'horizon':hk,'mean':em,'ci95':eci})
 if executable:return {'class':'C','label':'predictive + pre-fee executable indication','qualifying_information':qualifying,'qualifying_executable':executable}
 if qualifying:return {'class':'B','label':'predictive information, economics not established','qualifying_information':qualifying,'qualifying_executable':[]}
 return {'class':'A','label':'no usable indication under predeclared operational criteria','qualifying_information':[],'qualifying_executable':[]}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--output',required=True);a=ap.parse_args();root=Path(a.input).resolve();outdir=Path(a.output).resolve();outdir.mkdir(parents=True,exist_ok=True)
 mf,errs=audit_manifest(root);audit={m:Counter() for m in MARKETS}
 results={'schema':'m1a-results-v1','analyzer_version':VERSION,'freeze_manifest':mf,'predeclared':{'primary_market':PRIMARY,'exploratory_market':'BTC-USDC','grid_ms':500,'trade_lookback_ms':1000,'depth_levels':5,'horizons_ms':[500,1000,2000,5000],'bootstrap_block_seconds':60,'bootstrap_replicates':BOOTSTRAPS,'seed':SEED,'classification_rule':'Information qualifies only if top-bottom mean mid-return >0, 95% block-bootstrap CI lower bound >0, >=3/4 adjacent bin means nondecreasing, and contrast remains >0 in first half, second half, and after removing largest 1% absolute returns. C additionally requires top-decile ask-to-future-bid mean >0 with 95% block-bootstrap CI lower bound >0.'},'audit':{'manifest_errors':errs,'markets':{}},'markets':{}}
 if errs:raise SystemExit('Freeze hash audit failed: '+repr(errs))
 series={}
 for m in MARKETS:series[m]=build_series(root,m,audit);results['audit']['markets'][m]=dict(audit[m]);results['markets'][m]=analyze_market(series[m],m)
 rob=robustness(series[PRIMARY]);results['robustness_primary']=rob;results['classification']=classify(results['markets'][PRIMARY],rob);results=clean(results)
 (outdir/'results.json').write_text(json.dumps(results,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8')
 c=results['classification'];rawmeta=mf['files']['raw_events.jsonl']
 def fmt(v,n=4):
  return 'n/a' if v is None else f'{v:.{n}f}'
 lines=['# M1A Research Report','',
  '## 1. Dataset freeze',
  f'- Cutoff: {mf["research_cutoff_utc"]}',
  f'- Raw receive UTC ns range: {rawmeta.get("first_utc_ns")} .. {rawmeta.get("last_utc_ns")}',
  f'- Raw events: {rawmeta["records"]}; M0={mf.get("m0_version")}; analyzer={VERSION}.',
  '- Frozen file SHA-256 hashes are recorded in freeze_manifest.json; post-cutoff M0 data is not read.',
  '',
  '## 2. Valid analysis time and exclusions']
 for m in MARKETS:
  x=results['audit']['markets'][m];lines.append(f'- {m}: grid={x["grid_points"]}, valid={x["valid_grids"]} ({fmt(x["valid_analysis_seconds"],1)}s), invalid={x["invalid_grids"]}, checkpoints={x["checkpoint_count"]}, same-book-state fraction={fmt(x["same_bookstate_fraction"],3)}, zero-F3 fraction={fmt(x["zero_tradeflow_fraction"],3)}.')
 lines+=['','## 3. Data-quality audit']
 for m in MARKETS:
  x=results['audit']['markets'][m];lines.append(f'- {m}: crossed={x["crossed_grids"]}; negative sizes={x["negative_size_updates"]}; nonpositive prices={x["nonpositive_price_updates"]}; replay nonce anomalies={x["nonce_anomalies_replay"]}; monotonic regressions={x["monotonic_regressions"]}.')
 lines+=['','## 4. Feature distributions']
 for m in MARKETS:
  lines.append(f'### {m}')
  for fn,z in results['markets'][m]['features'].items():lines.append(f'- {fn}: N={z["distribution"]["n"]}; q10/q30/q70/q90={z["quantiles_10_30_70_90"]}.')
 lines+=['','## 5–10. Feature/horizon results, contrasts, executable markouts and bootstrap uncertainty']
 for m in MARKETS:
  lines+=['',f'### {m}' + (' (PRIMARY)' if m==PRIMARY else ' (EXPLORATORY)'),'| Feature | Horizon | N | Excluded | Top-bottom mid (bps) | 95% block CI (bps) | Monotone | Top10 ask→future-bid (bps) | Bottom10 downward response (bps) |','|---|---:|---:|---:|---:|---|---:|---:|---:|']
  for hk,h in results['markets'][m]['horizons'].items():
   for fn,z in h.items():
    b=z['top_minus_bottom_mid_return'];ci=b.get('ci95_bps',[None,None]);d0=z["groups"][0]["downward_sell_then_buy_response"].get("mean");lines.append(f'| {fn} | {hk} | {z["n"]} | {z["excluded_invalid_or_resync"]} | {fmt(b.get("mean_diff_bps"))} | [{fmt(ci[0])}, {fmt(ci[1])}] | {fmt(z["monotone_adjacent_fraction"],2)} | {fmt(z["top10_executable_mean_bps"])} | {fmt(d0*10000 if d0 is not None else None)} |')
 lines+=['','## 11. BTC-EUR robustness',f'- Activity split: {results["robustness_primary"]["active_rule"]}','| Feature | Horizon | First half bps | Second half bps | Quiet bps | Active bps | Trim 1% bps |','|---|---:|---:|---:|---:|---:|---:|']
 for fn,hs in results['robustness_primary']['tests'].items():
  for hk,z in hs.items():lines.append(f'| {fn} | {hk} | {fmt(z["first_half"]*10000 if z["first_half"] is not None else None)} | {fmt(z["second_half"]*10000 if z["second_half"] is not None else None)} | {fmt(z["quiet"]*10000 if z["quiet"] is not None else None)} | {fmt(z["active"]*10000 if z["active"] is not None else None)} | {fmt(z["trim_largest_abs_1pct"]*10000 if z["trim_largest_abs_1pct"] is not None else None)} |')
 lines+=['','## 12. BTC-USDC interpretation','BTC-USDC is exploratory only and never drives the M1A pass/fail classification. Sparse trade flow must not be interpreted as proof of no edge.','','## 13. Classification',f'**{c["class"]} — {c["label"]}**','',f'Qualifying information effects: {c["qualifying_information"] or "none"}.',f'Qualifying executable indications: {c["qualifying_executable"] or "none"}.','','## Interpretation boundary','This is an information-layer falsification test, not a trading strategy and not evidence of net profitability after fees/friction. No optimized thresholds or ML models are produced.']
 (outdir/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps({'results':str(outdir/'results.json'),'report':str(outdir/'report.md'),'classification':c},indent=2))
if __name__=='__main__':main()
