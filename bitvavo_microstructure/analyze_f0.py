#!/usr/bin/env python3
"""F0 — BTC/EUR vs BTC/USDC execution-topology analyzer.

Research-only. Consumes the completed 7-day prospective collector output and
computes paired executable book-walk friction/capacity diagnostics. It does not
place orders and does not optimize a trading strategy.
"""
from __future__ import annotations
import argparse, hashlib, json, math, random, statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

VERSION="1.0.0"
MIN_USABLE_PAIRS=8000
NOTIONALS_EUR=(50,100,250,500,1000,2500,5000,10000)
BOOTSTRAPS=10000
BOOT_SEED=20261003
# Public tier-0 schedule verified 2026-10-03. Keep explicit in output.
TAKER_EUR=0.0025
MAKER_EUR=0.0015
TAKER_USDC=0.0005
MAKER_USDC=0.0005
USDC_EUR_CONVERSION_FEE=0.0010
FEE_SOURCE_URL="https://bitvavo.com/nl/fees"
FEE_VERIFIED_DATE="2026-10-03"

def sha256_file(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def load_jsonl(p):
    with p.open(encoding="utf-8") as f:
        for n,line in enumerate(f,1):
            try: yield json.loads(line)
            except Exception as e: raise RuntimeError(f"{p}:{n}: invalid JSON: {e}")

def pct(xs,p):
    ys=sorted(float(x) for x in xs)
    if not ys:return None
    pos=(len(ys)-1)*p; lo=int(math.floor(pos)); hi=int(math.ceil(pos))
    if lo==hi:return ys[lo]
    w=pos-lo
    return ys[lo]*(1-w)+ys[hi]*w

def stats(xs):
    ys=[float(x) for x in xs if x is not None and math.isfinite(float(x))]
    if not ys:return {"n":0}
    return {
        "n":len(ys),"mean":statistics.fmean(ys),"median":statistics.median(ys),
        "p05":pct(ys,.05),"p25":pct(ys,.25),"p75":pct(ys,.75),"p95":pct(ys,.95),
        "min":min(ys),"max":max(ys)
    }

def parse_book(wrapper,market):
    if not wrapper.get("ok"): return None
    r=wrapper.get("response")
    if not isinstance(r,dict) or r.get("market")!=market:return None
    bids=r.get("bids"); asks=r.get("asks")
    if not bids or not asks:return None
    try:
        bids=[(float(p),float(q)) for p,q in bids if float(p)>0 and float(q)>0]
        asks=[(float(p),float(q)) for p,q in asks if float(p)>0 and float(q)>0]
    except Exception:
        return None
    if not bids or not asks:return None
    bids.sort(reverse=True); asks.sort()
    if bids[0][0]>=asks[0][0]:return None
    return {"bids":bids,"asks":asks,"bid":bids[0][0],"ask":asks[0][0],
            "mid":(bids[0][0]+asks[0][0])/2,
            "timestamp":r.get("timestamp"),"nonce":r.get("nonce"),
            "local_send_ms":wrapper.get("local_send_ms"),
            "local_recv_ms":wrapper.get("local_recv_ms"),
            "latency_ms":wrapper.get("latency_ms")}

def vwap(levels,qty_btc):
    remain=qty_btc; quote=0.0; walked=0
    for price,size in levels:
        take=min(remain,size)
        if take>0:
            quote += take*price; remain -= take; walked += 1
        if remain<=1e-15: break
    if remain>1e-12:return None
    return {"vwap":quote/qty_btc,"quote":quote,"levels":walked}

def bps(x): return x*10000.0

def roundtrip_cost_bps(buy_vwap,sell_vwap,fee):
    # Start/end in quote currency; fee charged on both legs.
    retained=(sell_vwap*(1-fee))/(buy_vwap*(1+fee))
    return bps(1-retained)

def one_way_slippage_bps(side_vwap,mid,side):
    if side=="buy":return bps(side_vwap/mid-1)
    return bps(1-side_vwap/mid)

def analyze_pair(rec):
    if not rec.get("both_ok"):return None,"pair_not_both_ok"
    books=rec.get("books",{})
    eur=parse_book(books.get("BTC-EUR",{}),"BTC-EUR")
    usdc=parse_book(books.get("BTC-USDC",{}),"BTC-USDC")
    if eur is None:return None,"invalid_btc_eur_book"
    if usdc is None:return None,"invalid_btc_usdc_book"
    if rec.get("depth")!=100:return None,"depth_not_100"
    t=int(rec.get("collector_start_ms",0))
    if t<=0:return None,"missing_pair_time"

    skew_local=None
    mids=[]
    for b in (eur,usdc):
        if b["local_send_ms"] is not None and b["local_recv_ms"] is not None:
            mids.append((b["local_send_ms"]+b["local_recv_ms"])/2)
    if len(mids)==2:skew_local=abs(mids[1]-mids[0])

    out={"pair_id":rec.get("pair_id"),"t_ms":t,"local_pair_midpoint_skew_ms":skew_local,
         "pair_elapsed_ms":rec.get("pair_elapsed_ms"),
         "latency_eur_ms":eur["latency_ms"],"latency_usdc_ms":usdc["latency_ms"],
         "spread_eur_bps":bps((eur["ask"]-eur["bid"])/eur["mid"]),
         "spread_usdc_bps":bps((usdc["ask"]-usdc["bid"])/usdc["mid"]),
         "notionals":{}}
    for n in NOTIONALS_EUR:
        qty=n/eur["mid"]  # identical BTC exposure, anchored to paired BTC/EUR mid
        eb=vwap(eur["asks"],qty); es=vwap(eur["bids"],qty)
        ub=vwap(usdc["asks"],qty); us=vwap(usdc["bids"],qty)
        row={"btc_qty":qty}
        if eb and es:
            row["EUR"]={
                "buy_vwap":eb["vwap"],"sell_vwap":es["vwap"],
                "buy_levels":eb["levels"],"sell_levels":es["levels"],
                "buy_slippage_bps":one_way_slippage_bps(eb["vwap"],eur["mid"],"buy"),
                "sell_slippage_bps":one_way_slippage_bps(es["vwap"],eur["mid"],"sell"),
                "prefee_roundtrip_cost_bps":bps(1-es["vwap"]/eb["vwap"]),
                "taker_taker_cost_bps":roundtrip_cost_bps(eb["vwap"],es["vwap"],TAKER_EUR),
                "maker_maker_fee_sensitivity_bps":roundtrip_cost_bps(eb["vwap"],es["vwap"],MAKER_EUR)
            }
        else: row["EUR"]={"insufficient_depth":True}
        if ub and us:
            base={
                "buy_vwap":ub["vwap"],"sell_vwap":us["vwap"],
                "buy_levels":ub["levels"],"sell_levels":us["levels"],
                "buy_slippage_bps":one_way_slippage_bps(ub["vwap"],usdc["mid"],"buy"),
                "sell_slippage_bps":one_way_slippage_bps(us["vwap"],usdc["mid"],"sell"),
                "prefee_roundtrip_cost_bps":bps(1-us["vwap"]/ub["vwap"]),
                "taker_taker_cost_bps":roundtrip_cost_bps(ub["vwap"],us["vwap"],TAKER_USDC),
                "maker_maker_fee_sensitivity_bps":roundtrip_cost_bps(ub["vwap"],us["vwap"],MAKER_USDC)
            }
            # Fee-only per-cycle funding stress: two USDC/EUR conversions; excludes conversion spread/slippage.
            retained=(1-base["taker_taker_cost_bps"]/10000.0)*(1-USDC_EUR_CONVERSION_FEE)/(1+USDC_EUR_CONVERSION_FEE)
            base["taker_taker_plus_conversion_fee_only_bps"]=bps(1-retained)
            row["USDC"]=base
        else: row["USDC"]={"insufficient_depth":True}
        if "taker_taker_cost_bps" in row["EUR"] and "taker_taker_cost_bps" in row["USDC"]:
            row["paired_delta_bps_usdc_minus_eur"]=row["USDC"]["taker_taker_cost_bps"]-row["EUR"]["taker_taker_cost_bps"]
        out["notionals"][str(n)]=row
    return out,None

def hour_key(ms):
    return ms//3_600_000

def day_key(ms):
    return datetime.fromtimestamp(ms/1000,timezone.utc).strftime("%Y-%m-%d")

def block_bootstrap_mean(rows,field_getter):
    blocks=defaultdict(list)
    for r in rows:
        v=field_getter(r)
        if v is not None and math.isfinite(float(v)):blocks[hour_key(r["t_ms"])].append(float(v))
    block_values=[v for _,v in sorted(blocks.items()) if v]
    if not block_values:return {"blocks":0,"replicates":0,"mean":None,"ci95":[None,None]}
    observed=statistics.fmean([x for b in block_values for x in b])
    rng=random.Random(BOOT_SEED); sims=[]; nb=len(block_values)
    for _ in range(BOOTSTRAPS):
        sample=[]
        for _j in range(nb): sample.extend(block_values[rng.randrange(nb)])
        sims.append(statistics.fmean(sample))
    return {"blocks":nb,"replicates":BOOTSTRAPS,"mean":observed,"ci95":[pct(sims,.025),pct(sims,.975)]}

def summarize(rows):
    result={
        "version":VERSION,
        "usable_pairs":len(rows),
        "minimum_required_pairs":MIN_USABLE_PAIRS,
        "minimum_gate_pass":len(rows)>=MIN_USABLE_PAIRS,
        "fees":{
            "source":FEE_SOURCE_URL,
            "verified_date":FEE_VERIFIED_DATE,
            "BTC-EUR_taker":TAKER_EUR,
            "BTC-EUR_maker":MAKER_EUR,
            "BTC-USDC_taker":TAKER_USDC,
            "BTC-USDC_maker":MAKER_USDC,
            "USDC-EUR_conversion_fee":USDC_EUR_CONVERSION_FEE,
            "one_time_usdc_funding_fee_bps":USDC_EUR_CONVERSION_FEE*10000.0,
            "one_time_funding_note":"A single one-way USDC funding conversion fee is reported separately; amortized cost per cycle = one_time_usdc_funding_fee_bps / number_of_cycles.",
            "maker_note":"maker/maker values are fee sensitivity only; snapshot data cannot establish passive fill probability or adverse selection.",
            "conversion_note":"per-cycle funding stress includes conversion fees only; USDC/EUR spread/slippage/basis not measured by this collector"
        },
        "pairing":{
            "local_midpoint_skew_ms":stats([r["local_pair_midpoint_skew_ms"] for r in rows if r["local_pair_midpoint_skew_ms"] is not None]),
            "pair_elapsed_ms":stats([r["pair_elapsed_ms"] for r in rows if r["pair_elapsed_ms"] is not None]),
            "latency_eur_ms":stats([r["latency_eur_ms"] for r in rows if r["latency_eur_ms"] is not None]),
            "latency_usdc_ms":stats([r["latency_usdc_ms"] for r in rows if r["latency_usdc_ms"] is not None])
        },
        "spread":{
            "BTC-EUR_bps":stats([r["spread_eur_bps"] for r in rows]),
            "BTC-USDC_bps":stats([r["spread_usdc_bps"] for r in rows])
        },
        "notionals":{},
        "per_day":{}
    }
    for n in NOTIONALS_EUR:
        k=str(n)
        eur=[r["notionals"][k]["EUR"] for r in rows]
        usd=[r["notionals"][k]["USDC"] for r in rows]
        deltas=[r["notionals"][k].get("paired_delta_bps_usdc_minus_eur") for r in rows]
        paired=[x for x in deltas if x is not None]
        result["notionals"][k]={
            "EUR":{
                "insufficient_depth_n":sum(1 for x in eur if x.get("insufficient_depth")),
                "prefee_roundtrip_cost_bps":stats([x.get("prefee_roundtrip_cost_bps") for x in eur]),
                "taker_taker_cost_bps":stats([x.get("taker_taker_cost_bps") for x in eur]),
                "maker_maker_fee_sensitivity_bps":stats([x.get("maker_maker_fee_sensitivity_bps") for x in eur]),
                "buy_slippage_bps":stats([x.get("buy_slippage_bps") for x in eur]),
                "sell_slippage_bps":stats([x.get("sell_slippage_bps") for x in eur]),
                "buy_levels":stats([x.get("buy_levels") for x in eur]),
                "sell_levels":stats([x.get("sell_levels") for x in eur])
            },
            "USDC":{
                "insufficient_depth_n":sum(1 for x in usd if x.get("insufficient_depth")),
                "prefee_roundtrip_cost_bps":stats([x.get("prefee_roundtrip_cost_bps") for x in usd]),
                "taker_taker_cost_bps":stats([x.get("taker_taker_cost_bps") for x in usd]),
                "maker_maker_fee_sensitivity_bps":stats([x.get("maker_maker_fee_sensitivity_bps") for x in usd]),
                "fee_only_per_cycle_funding_bps":stats([x.get("taker_taker_plus_conversion_fee_only_bps") for x in usd]),
                "buy_slippage_bps":stats([x.get("buy_slippage_bps") for x in usd]),
                "sell_slippage_bps":stats([x.get("sell_slippage_bps") for x in usd]),
                "buy_levels":stats([x.get("buy_levels") for x in usd]),
                "sell_levels":stats([x.get("sell_levels") for x in usd])
            },
            "paired_delta_bps_usdc_minus_eur":stats(paired),
            "usdc_cheaper_fraction":(sum(1 for x in paired if x<0)/len(paired)) if paired else None,
            "one_hour_block_bootstrap_mean_delta":block_bootstrap_mean(rows,lambda r:r["notionals"][k].get("paired_delta_bps_usdc_minus_eur"))
        }
    byday=defaultdict(list)
    for r in rows:byday[day_key(r["t_ms"])].append(r)
    for d,rr in sorted(byday.items()):
        result["per_day"][d]={"usable_pairs":len(rr),"notionals":{}}
        for n in NOTIONALS_EUR:
            k=str(n); vals=[r["notionals"][k].get("paired_delta_bps_usdc_minus_eur") for r in rr]
            result["per_day"][d]["notionals"][k]={"paired_delta_bps":stats(vals)}
    return result

def audit_trades(path):
    if not path.exists():return {"present":False}
    windows=0;ok=0;trunc=0;counts=defaultdict(int)
    ids=defaultdict(set);dups=defaultdict(int)
    for rec in load_jsonl(path):
        windows+=1;m=rec.get("market","?")
        req=rec.get("request",{})
        if req.get("ok"):
            ok+=1
            if req.get("possible_truncation"):trunc+=1
            data=req.get("response")
            if isinstance(data,list):
                counts[m]+=len(data)
                for t in data:
                    tid=t.get("id")
                    if tid is not None:
                        if tid in ids[m]:dups[m]+=1
                        ids[m].add(tid)
    return {"present":True,"windows":windows,"ok_windows":ok,"possible_truncation_windows":trunc,
            "raw_trade_rows":dict(counts),"unique_trade_ids":{m:len(s) for m,s in ids.items()},
            "duplicate_trade_ids_seen_across_overlapping_windows":dict(dups)}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True)
    ap.add_argument("--output",required=True)
    a=ap.parse_args()
    root=Path(a.input).resolve(); out=Path(a.output).resolve(); out.mkdir(parents=True,exist_ok=True)
    books=root/"paired_books.jsonl"
    if not books.exists():raise SystemExit(f"missing {books}")
    rows=[];excluded=defaultdict(int);attempted=0
    for rec in load_jsonl(books):
        attempted+=1;r,reason=analyze_pair(rec)
        if r is None:excluded[reason]+=1
        else:rows.append(r)
    summary=summarize(rows)
    summary["input"]={
        "root":str(root),"paired_books_sha256":sha256_file(books),
        "attempted_pairs":attempted,"excluded":dict(sorted(excluded.items())),
        "trade_windows":audit_trades(root/"trade_windows.jsonl")
    }
    (out/"f0_results.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    report=[
        "# F0 — BTC/EUR vs BTC/USDC execution topology","",
        f"- Analyzer: {VERSION}",
        f"- Usable paired snapshots: {len(rows)} / {attempted}",
        f"- Pre-registered minimum >= {MIN_USABLE_PAIRS}: **{'PASS' if summary['minimum_gate_pass'] else 'FAIL'}**",
        f"- Fee schedule verified: {FEE_VERIFIED_DATE} — {FEE_SOURCE_URL}",
        "- Primary economics: public tier-0 taker/taker fees; maker/maker is fee sensitivity only, not a fill claim.",
        "- USDC per-cycle funding stress includes conversion fees only; USDC/EUR conversion spread/slippage/basis remain unmeasured.","",
        "## Capacity / paired delta (USDC minus EUR, bp)"
    ]
    for n in NOTIONALS_EUR:
        s=summary["notionals"][str(n)]
        d=s["paired_delta_bps_usdc_minus_eur"]; ci=s["one_hour_block_bootstrap_mean_delta"]["ci95"]
        report.append(f"- €{n}: median={d.get('median')}, mean={d.get('mean')}, 95% block-bootstrap mean CI={ci}, USDC cheaper fraction={s['usdc_cheaper_fraction']}, insufficient depth EUR/USDC={s['EUR']['insufficient_depth_n']}/{s['USDC']['insufficient_depth_n']}")
    (out/"f0_report.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    print(json.dumps({"minimum_gate_pass":summary["minimum_gate_pass"],"usable_pairs":len(rows),
                      "results":str(out/"f0_results.json"),"report":str(out/"f0_report.md")},indent=2))

if __name__=="__main__":
    main()
