#!/usr/bin/env python3
"""Quality report for Bitvavo M0 raw event capture."""
import argparse,json,statistics
from collections import Counter,defaultdict
from pathlib import Path

def pct(xs,p):
    if not xs:return None
    ys=sorted(xs); return ys[min(len(ys)-1,round((len(ys)-1)*p))]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--input",required=True); a=ap.parse_args()
    root=Path(a.input); raw=root/"raw_events.jsonl"; ses=root/"sessions.jsonl"
    trades=Counter(); books=Counter(); ids=defaultdict(set); dup=Counter(); regress=Counter(); last_ts={}
    delays=defaultdict(list)
    if raw.exists():
      for line in raw.open(encoding="utf-8"):
        try:r=json.loads(line); x=r["raw"]
        except:continue
        m=x.get("market"); ev=x.get("event")
        if ev=="trade":
          trades[m]+=1; tid=x.get("id")
          if tid in ids[m]:dup[m]+=1
          if tid:ids[m].add(tid)
          ts=x.get("timestampNs")
          if ts is not None:
            ts=int(ts)
            if m in last_ts and ts<last_ts[m]:regress[m]+=1
            last_ts[m]=ts; delays[m].append(r["recv_utc_ns"]-ts)
        elif ev=="book": books[m]+=1
    kinds=Counter(); gaps=Counter(); duplicates=Counter(); stale=Counter(); valid=Counter(); disconnects=0
    if ses.exists():
      for line in ses.open(encoding="utf-8"):
        try:x=json.loads(line)
        except:continue
        k=x.get("kind"); kinds[k]+=1
        if k in ("nonce_gap","forward_nonce_gap"):gaps[x.get("market")]+=1
        if k=="duplicate_nonce":duplicates[x.get("market")]+=1
        if k=="stale_nonce":stale[x.get("market")]+=1
        if k=="book_valid":valid[x.get("market")]+=1
        if k=="disconnect":disconnects+=1
    out={"trades":{},"books":{},"collector":{"events":dict(kinds),"disconnects":disconnects},
         "files":{p.name:p.stat().st_size for p in (raw,ses) if p.exists()}}
    for m in ("BTC-EUR","BTC-USDC"):
      ds=delays[m]
      out["trades"][m]={"events":trades[m],"unique_ids":len(ids[m]),"duplicate_ids":dup[m],
        "timestamp_regressions":regress[m],
        "receive_minus_exchange_ns":{"p50":pct(ds,.5),"p90":pct(ds,.9),"p99":pct(ds,.99),
          "negative":sum(v<0 for v in ds)}}
      out["books"][m]={"updates":books[m],"forward_nonce_gaps":gaps[m],
        "duplicate_nonces":duplicates[m],"stale_nonces":stale[m],"book_valid_events":valid[m]}
    (root/"quality_report.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
    print(json.dumps(out,indent=2))

if __name__=="__main__":main()
