#!/usr/bin/env python3
"""M1A-PREREG-v1.3 executor (content rules identical to v1.2). Research only; no trading."""
from __future__ import annotations
import argparse, bisect, hashlib, json, math, random, statistics
from collections import Counter, deque
from pathlib import Path

VERSION = "1.2.0"
PROTOCOL = "M1A-PREREG-v1.3"
CONTENT_PROTOCOL = "M1A-PREREG-v1.2"
PRIMARY = "BTC-EUR"
EXPLORATORY = "BTC-USDC"
MARKETS = (PRIMARY, EXPLORATORY)

GRID_NS = 500_000_000
LOOKBACK_NS = 1_000_000_000
HORIZONS_NS = (500_000_000, 1_000_000_000, 2_000_000_000, 5_000_000_000)
PRIMARY_H_NS = 1_000_000_000
BLOCK_NS = 60_000_000_000
BLOCK_POINTS = BLOCK_NS // GRID_NS
BOOTSTRAPS = 10_000
SEED = 20261002

MIN_TOTAL = 3600
MIN_HOLDOUT = 1440
MIN_HOLDOUT_SECONDS = 1800
MIN_FULL_BLOCKS = 10
MIN_QUANTILE_GROUP = 30
MIN_TRIMMED = 1000

INVALID_KINDS = {
    "connect", "disconnect", "duplicate_nonce", "stale_nonce", "forward_nonce_gap",
    "nonce_gap", "resync_failed", "resync_exception", "ws_error", "run_exception"
}

def clean_json(x):
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: clean_json(v) for k,v in x.items()}
    if isinstance(x, list):
        return [clean_json(v) for v in x]
    return x

def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

def sha256_file(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def load_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            try:
                yield json.loads(line)
            except Exception as e:
                raise RuntimeError(f"{path}:{ln}: invalid JSON: {e}")

def qtile(xs, p):
    ys = sorted(float(x) for x in xs if x is not None and math.isfinite(float(x)))
    if not ys:
        return math.nan
    pos = (len(ys) - 1) * p
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ys[lo]
    w = pos - lo
    return ys[lo] * (1 - w) + ys[hi] * w

def descriptive(xs):
    ys = [float(x) for x in xs if x is not None and math.isfinite(float(x))]
    if not ys:
        return {"n": 0, "mean": None, "median": None, "std": None}
    return {
        "n": len(ys),
        "mean": statistics.fmean(ys),
        "median": statistics.median(ys),
        "std": statistics.stdev(ys) if len(ys) >= 2 else 0.0,
    }

def rankdata(values):
    pairs = sorted((float(v), i) for i, v in enumerate(values))
    ranks = [0.0] * len(pairs)
    i = 0
    while i < len(pairs):
        j = i + 1
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        avg = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[pairs[k][1]] = avg
        i = j
    return ranks

def pearson(x, y):
    n = len(x)
    if n < 2:
        return math.nan
    mx, my = statistics.fmean(x), statistics.fmean(y)
    dx = [v - mx for v in x]
    dy = [v - my for v in y]
    sx = sum(v*v for v in dx)
    sy = sum(v*v for v in dy)
    if sx <= 0 or sy <= 0:
        return math.nan
    return sum(a*b for a,b in zip(dx,dy)) / math.sqrt(sx*sy)

def spearman(x, y):
    if len(x) != len(y) or len(x) < 2:
        return math.nan
    return pearson(rankdata(x), rankdata(y))

def imbalance(b, a):
    d = b + a
    return (b-a)/d if d > 0 else math.nan

def book_metrics(bids, asks):
    bp = sorted(((float(p), float(s)) for p,s in bids.items() if float(s) > 0), reverse=True)[:5]
    ap = sorted(((float(p), float(s)) for p,s in asks.items() if float(s) > 0))[:5]
    if not bp or not ap:
        return None
    bid, bs = bp[0]
    ask, az = ap[0]
    if bid <= 0 or ask <= 0 or bid >= ask:
        return None
    return {
        "bid": bid,
        "ask": ask,
        "mid": (bid+ask)/2.0,
        "f1": imbalance(bs, az),
        "f2": imbalance(sum(s for _,s in bp), sum(s for _,s in ap)),
    }

def apply_book(book, msg):
    for side in ("bids", "asks"):
        d = book[side]
        for p,s in msg.get(side, []):
            if float(s) == 0:
                d.pop(p, None)
            else:
                d[p] = s
    book["nonce"] = int(msg["nonce"])

def audit_manifest(root: Path):
    mf = json.loads((root/"freeze_manifest.json").read_text(encoding="utf-8"))
    errors = []
    if mf.get("m0_version") != "1.0.5":
        errors.append(f'm0_version must equal 1.0.5, got {mf.get("m0_version")!r}')
    for name in ("raw_events.jsonl", "sessions.jsonl", "book_checkpoints.jsonl"):
        meta = mf.get("files", {}).get(name)
        p = root/name
        if not meta or not p.exists():
            errors.append(f"missing manifest/file entry: {name}")
            continue
        actual = sha256_file(p)
        if actual != meta.get("sha256"):
            errors.append(f"hash mismatch: {name}")
    return mf, errors

def build_grid(root: Path, market: str):
    checkpoints = sorted(
        (x for x in load_jsonl(root/"book_checkpoints.jsonl") if x.get("market")==market),
        key=lambda x: int(x["mono_ns"])
    )
    if not checkpoints:
        raise RuntimeError(f"{market}: no persisted book checkpoint")

    last = -1
    regressions = 0
    for r in load_jsonl(root/"raw_events.jsonl"):
        t = int(r["recv_mono_ns"])
        if last >= 0 and t < last:
            regressions += 1
        last = t
    if regressions:
        raise RuntimeError(f"monotonic receive clock regressed {regressions} times")

    invalid_times = sorted(
        int(x["mono_ns"]) for x in load_jsonl(root/"sessions.jsonl")
        if x.get("kind") in INVALID_KINDS and x.get("market") in (None, market)
    )

    first_cp = checkpoints[0]
    cp_i = 0
    cp_t = int(first_cp["mono_ns"])
    book = {"bids": dict(first_cp["bids"]), "asks": dict(first_cp["asks"]), "nonce": int(first_cp["nonce"])}
    valid = True
    segment = 0
    next_cp_t = int(checkpoints[1]["mono_ns"]) if len(checkpoints)>1 else None

    def cp_valid_at(t, checkpoint_time):
        ii = bisect.bisect_right(invalid_times, t) - 1
        return ii < 0 or invalid_times[ii] < checkpoint_time

    # A persisted checkpoint opens a new causal segment. Trade-flow state starts empty:
    # no TFI lookback is allowed to cross the segment boundary.
    trades = deque()

    def market_events():
        for r in load_jsonl(root/"raw_events.jsonl"):
            msg=r.get("raw",{})
            if msg.get("market")==market and int(r["recv_mono_ns"])>=cp_t:
                yield r

    events=market_events()
    try:
        current=next(events)
    except StopIteration:
        current=None

    next_grid = ((cp_t + GRID_NS - 1)//GRID_NS)*GRID_NS
    rows = []
    audit = Counter()
    audit["checkpoint_count"] = len(checkpoints)

    while current is not None or next_cp_t is not None:
        event_t = int(current["recv_mono_ns"]) if current is not None else 2**63-1
        boundary = min(event_t, next_cp_t if next_cp_t is not None else 2**63-1)

        while next_grid < boundary:
            while trades and trades[0][0] <= next_grid-LOOKBACK_NS:
                trades.popleft()
            buy = sum(v for t,side,v in trades if t <= next_grid and side=="buy")
            sell = sum(v for t,side,v in trades if t <= next_grid and side=="sell")
            f3 = imbalance(buy, sell) if buy+sell>0 else 0.0
            if buy+sell==0:
                audit["zero_tradeflow_grids"] += 1

            met = book_metrics(book["bids"], book["asks"]) if valid and cp_valid_at(next_grid, cp_t) else None
            if met is None:
                audit["invalid_grids"] += 1
                rows.append({"t":next_grid,"segment":segment,"valid":False,"bid":None,"ask":None,"mid":None,
                             "f1":None,"f2":None,"f3":f3})
            else:
                rows.append({"t":next_grid,"segment":segment,"valid":True,**met,"f3":f3})
                audit["valid_grids"] += 1
            next_grid += GRID_NS

        if next_cp_t is not None and next_cp_t <= event_t:
            cp_i += 1
            cp = checkpoints[cp_i]
            cp_t = int(cp["mono_ns"])
            book = {"bids":dict(cp["bids"]), "asks":dict(cp["asks"]), "nonce":int(cp["nonce"])}
            valid = True
            segment += 1
            # Hard segment boundary: TFI may use only trades received after this checkpoint.
            trades.clear()
            audit["tradeflow_segment_resets"] += 1
            next_cp_t = int(checkpoints[cp_i+1]["mono_ns"]) if cp_i+1 < len(checkpoints) else None
            continue

        if current is None:
            break

        msg = current["raw"]
        t = int(current["recv_mono_ns"])
        if msg.get("event")=="trade":
            try:
                trades.append((t,msg["side"],float(msg["amount"])))
                audit["trade_events"] += 1
            except Exception:
                audit["malformed_trades"] += 1
        elif msg.get("event")=="book":
            n = int(msg["nonce"])
            if valid and n == int(book["nonce"])+1:
                apply_book(book,msg)
                audit["book_updates"] += 1
            elif valid:
                valid = False
                audit["nonce_anomalies_replay"] += 1

        try:
            current=next(events)
        except StopIteration:
            current=None

    audit["grid_points"] = len(rows)
    audit["monotonic_regressions"] = regressions
    return rows, dict(audit)

def row_target(rows, i, h_ns):
    step = h_ns // GRID_NS
    j = i + step
    if j >= len(rows):
        return None
    window = rows[i:j+1]
    if len(window) != step + 1:
        return None
    segment = window[0]["segment"]
    for k, row in enumerate(window):
        if not row["valid"] or row["segment"] != segment:
            return None
        if k and row["t"] - window[k-1]["t"] != GRID_NS:
            return None
    if window[-1]["t"] - window[0]["t"] != h_ns:
        return None
    return 1e4 * ((window[-1]["mid"] - window[0]["mid"]) / window[0]["mid"])

def primary_eligible(rows):
    out=[]
    for i,r in enumerate(rows):
        if not r["valid"] or r["f1"] is None or not math.isfinite(r["f1"]):
            continue
        y = row_target(rows,i,PRIMARY_H_NS)
        if y is not None and math.isfinite(y):
            out.append(i)
    return out

def rows_for(rows, indices, feature, h_ns):
    out=[]
    for i in indices:
        x = rows[i].get(feature)
        if x is None or not math.isfinite(float(x)):
            continue
        y = row_target(rows,i,h_ns)
        if y is None or not math.isfinite(float(y)):
            continue
        out.append((rows[i]["t"], rows[i]["segment"], float(x), float(y)))
    return out

def split_primary(rows):
    eligible = primary_eligible(rows)
    nd = math.floor(0.60 * len(eligible))
    discovery = eligible[:nd]
    holdout = eligible[nd:]
    boundary_t = rows[holdout[0]]["t"] if holdout else None
    return eligible, discovery, holdout, boundary_t

def indices_by_boundary(rows, boundary_t, part):
    if boundary_t is None:
        return []
    if part=="discovery":
        return [i for i,r in enumerate(rows) if r["t"] < boundary_t]
    return [i for i,r in enumerate(rows) if r["t"] >= boundary_t]

def full_60s_blocks(primary_holdout_rows):
    if not primary_holdout_rows:
        return 0
    total=0
    run=1
    for a,b in zip(primary_holdout_rows, primary_holdout_rows[1:]):
        if b[1]==a[1] and b[0]-a[0]==GRID_NS:
            run += 1
        else:
            total += run // BLOCK_POINTS
            run=1
    total += run // BLOCK_POINTS
    return total

def moving_block_candidates(rows4):
    cands=[]
    n=len(rows4)
    for i in range(n):
        j=i+BLOCK_POINTS
        if j>n:
            break
        block=rows4[i:j]
        if block[-1][1] != block[0][1]:
            continue
        good=True
        for a,b in zip(block,block[1:]):
            if b[1]!=a[1] or b[0]-a[0]!=GRID_NS:
                good=False;break
        if good:
            cands.append(block)
    return cands

def bootstrap_spearman(rows4):
    obs = spearman([r[2] for r in rows4],[r[3] for r in rows4])
    cands=moving_block_candidates(rows4)
    if not cands:
        return {"rho":obs,"replicates":0,"p_boot":None,"ci95":[None,None],"candidate_blocks":0}
    rng=random.Random(SEED)
    sims=[]
    n=len(rows4)
    while len(sims)<BOOTSTRAPS:
        sample=[]
        while len(sample)<n:
            sample.extend(cands[rng.randrange(len(cands))])
        sample=sample[:n]
        rho=spearman([r[2] for r in sample],[r[3] for r in sample])
        if math.isfinite(rho):
            sims.append(rho)
        else:
            return {"rho":obs,"replicates":len(sims),"p_boot":None,"ci95":[None,None],
                    "candidate_blocks":len(cands),"error":"undefined bootstrap rho"}
    p=(1+sum(r<=0 for r in sims))/(BOOTSTRAPS+1)
    return {"rho":obs,"replicates":len(sims),"p_boot":p,
            "ci95":[qtile(sims,.025),qtile(sims,.975)],"candidate_blocks":len(cands)}

def quarter_rhos(rows4):
    n=len(rows4)
    out=[]
    for k in range(4):
        lo=math.floor(k*n/4); hi=math.floor((k+1)*n/4)
        q=rows4[lo:hi]
        out.append(spearman([r[2] for r in q],[r[3] for r in q]) if len(q)>=2 else math.nan)
    return out

def trimmed_rho(rows4):
    ys=[r[3] for r in rows4]
    lo,hi=qtile(ys,.01),qtile(ys,.99)
    kept=[r for r in rows4 if r[3]>=lo and r[3]<=hi]
    rho=spearman([r[2] for r in kept],[r[3] for r in kept]) if len(kept)>=2 else math.nan
    return {"q01":lo,"q99":hi,"n":len(kept),"rho":rho}

def quantile_contrast(rows4,q20,q80):
    low=[r[3] for r in rows4 if r[2]<=q20]
    high=[r[3] for r in rows4 if r[2]>=q80]
    contrast=(statistics.fmean(high)-statistics.fmean(low)) if low and high else math.nan
    return {"low_n":len(low),"high_n":len(high),"contrast_bps":contrast,
            "low_mean_bps":statistics.fmean(low) if low else None,
            "high_mean_bps":statistics.fmean(high) if high else None}

def feature_summary(rows4):
    return {"feature":descriptive([r[2] for r in rows4]),"target_bps":descriptive([r[3] for r in rows4]),
            "rho":spearman([r[2] for r in rows4],[r[3] for r in rows4]) if len(rows4)>=2 else None}

def analyze_market(rows, market):
    eligible, disc_primary, hold_primary, boundary_t=split_primary(rows)
    features={"f1":"L1_imbalance","f2":"D5_imbalance","f3":"TFI_1s"}
    q={}
    for f in features:
        vals=[rows[i][f] for i in disc_primary if rows[i].get(f) is not None and math.isfinite(float(rows[i][f]))]
        q[f]={"q20":qtile(vals,.20),"q80":qtile(vals,.80)}

    result={
        "market":market,
        "primary_eligible_n":len(eligible),
        "discovery_n":len(disc_primary),
        "holdout_n":len(hold_primary),
        "holdout_boundary_mono_ns":boundary_t,
        "discovery_period_mono_ns":[rows[disc_primary[0]]["t"],rows[disc_primary[-1]]["t"]] if disc_primary else [None,None],
        "holdout_period_mono_ns":[rows[hold_primary[0]]["t"],rows[hold_primary[-1]]["t"]] if hold_primary else [None,None],
        "quantiles_from_discovery":q,
        "feature_horizon":{}
    }
    d_idx=indices_by_boundary(rows,boundary_t,"discovery")
    h_idx=indices_by_boundary(rows,boundary_t,"holdout")
    for f,label in features.items():
        result["feature_horizon"][label]={}
        for h in HORIZONS_NS:
            drows=rows_for(rows,d_idx,f,h)
            hrows=rows_for(rows,h_idx,f,h)
            result["feature_horizon"][label][f"{h/1e9:g}s"]={
                "discovery":feature_summary(drows),
                "holdout":feature_summary(hrows),
                "missing_discovery":max(0,len(d_idx)-len(drows)),
                "missing_holdout":max(0,len(h_idx)-len(hrows)),
            }
    if market==PRIMARY:
        prows=rows_for(rows,hold_primary,"f1",PRIMARY_H_NS)
        boot=bootstrap_spearman(prows)
        quarters=quarter_rhos(prows)
        trim=trimmed_rho(prows)
        contrast=quantile_contrast(prows,q["f1"]["q20"],q["f1"]["q80"])
        blocks=full_60s_blocks(prows)
        hold_seconds=len(prows)*0.5
        min_checks={
            "primary_eligible_total":len(eligible)>=MIN_TOTAL,
            "holdout_primary_eligible":len(prows)>=MIN_HOLDOUT,
            "holdout_valid_seconds":hold_seconds>=MIN_HOLDOUT_SECONDS,
            "valid_60s_blocks":blocks>=MIN_FULL_BLOCKS,
            "four_quarters_nonempty":all(math.floor((k+1)*len(prows)/4)>math.floor(k*len(prows)/4) for k in range(4)),
            "q20_group_holdout":contrast["low_n"]>=MIN_QUANTILE_GROUP,
            "q80_group_holdout":contrast["high_n"]>=MIN_QUANTILE_GROUP,
            "trimmed_holdout":trim["n"]>=MIN_TRIMMED,
            "statistics_defined":all([
                math.isfinite(boot["rho"]) if boot["rho"] is not None else False,
                boot["p_boot"] is not None,
                boot["ci95"][0] is not None,
                math.isfinite(contrast["contrast_bps"]),
                all(math.isfinite(x) for x in quarters),
                math.isfinite(trim["rho"])
            ])
        }
        if not all(min_checks.values()):
            decision="INCONCLUSIVE"
            pass_checks={}
        else:
            pass_checks={
                "rho_gt_0":boot["rho"]>0,
                "p_boot_lt_0_05":boot["p_boot"]<0.05,
                "ci95_lower_gt_0":boot["ci95"][0]>0,
                "q80_minus_q20_gt_0":contrast["contrast_bps"]>0,
                "at_least_3_of_4_quarters_positive":sum(x>0 for x in quarters)>=3,
                "trimmed_rho_gt_0":trim["rho"]>0
            }
            decision="PASS" if all(pass_checks.values()) else "FAIL"
        result["confirmatory"]={
            "holdout_rows":len(prows),
            "holdout_valid_seconds":hold_seconds,
            "full_nonoverlap_60s_blocks":blocks,
            "bootstrap":boot,
            "q20_q80":contrast,
            "quarter_rhos":quarters,
            "trim":trim,
            "minimum_data_checks":min_checks,
            "pass_checks":pass_checks,
            "decision":decision
        }
    return result

def make_report(results):
    p=results["markets"][PRIMARY]
    c=p["confirmatory"]
    b=c["bootstrap"]
    q=c["q20_q80"]
    lines=[
        "# M1A-PREREG-v1.3 Report","",
        f"- Executor: {VERSION}",
        f"- Protocol: {PROTOCOL} (content rules {CONTENT_PROTOCOL})",
        f"- Freeze cutoff: {results['freeze_manifest'].get('research_cutoff_utc')}",
        f"- Decision: **{c['decision']}**","",
        "## Primary confirmatory HOLDOUT",
        f"- N: {c['holdout_rows']}",
        f"- valid observation seconds: {c['holdout_valid_seconds']}",
        f"- non-overlapping full 60s blocks: {c['full_nonoverlap_60s_blocks']}",
        f"- Spearman rho: {b['rho']}",
        f"- bootstrap p(one-sided): {b['p_boot']}",
        f"- percentile 95% CI: {b['ci95']}",
        f"- q80-q20 contrast (bp): {q['contrast_bps']} (high N={q['high_n']}, low N={q['low_n']})",
        f"- HOLDOUT quarter rhos: {c['quarter_rhos']}",
        f"- signed 1%/99% trimmed rho: {c['trim']['rho']} (N={c['trim']['n']})","",
        "## Minimum-data gate",
        *[f"- {k}: {v}" for k,v in c["minimum_data_checks"].items()],
        "","## PASS gate",
        *([f"- {k}: {v}" for k,v in c["pass_checks"].items()] if c["pass_checks"] else ["- not evaluated (INCONCLUSIVE)"]),
        "","## Boundary",
        "This is an information-layer falsification test. It is not a trading strategy and contains no fee/P&L claim."
    ]
    return "\n".join(lines)+"\n"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True)
    ap.add_argument("--output",required=True)
    args=ap.parse_args()
    root=Path(args.input).resolve()
    out=Path(args.output).resolve()
    out.mkdir(parents=True,exist_ok=True)

    mf,errors=audit_manifest(root)
    if errors:
        raise SystemExit("Freeze audit failed: "+"; ".join(errors))

    results={
        "schema":"m1a-prereg-v1.3-results-v1",
        "executor_version":VERSION,
        "protocol":PROTOCOL,
        "content_protocol":CONTENT_PROTOCOL,
        "freeze_manifest":mf,
        "audit":{},
        "markets":{}
    }
    for market in MARKETS:
        try:
            rows,audit=build_grid(root,market)
            results["audit"][market]=audit
            results["markets"][market]=analyze_market(rows,market)
        except RuntimeError as e:
            if market==PRIMARY:
                raise
            results["audit"][market]={"error":str(e)}
            results["markets"][market]={"market":market,"descriptive_status":"unavailable","error":str(e)}

    results=clean_json(results)
    (out/"results.json").write_text(json.dumps(results,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
    (out/"report.md").write_text(make_report(results),encoding="utf-8")
    print(json.dumps({"decision":results["markets"][PRIMARY]["confirmatory"]["decision"],
                      "results":str(out/"results.json"),"report":str(out/"report.md")},indent=2))

if __name__=="__main__":
    main()
