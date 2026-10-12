#!/usr/bin/env python3
"""Outcome-blind readiness estimate for M0 v1.0.6 before M1A_FREEZE_002.

This does NOT calculate M1A features, targets, discovery/holdout statistics,
or inspect market outcomes. It only measures causal book-valid coverage from
collector integrity/session metadata and the latest raw receive timestamp.

The threshold is operational margin, not a preregistered PASS/FAIL rule.
"""
from __future__ import annotations
import argparse, json, os
from collections import Counter
from pathlib import Path

M0_VERSION="1.0.6"
PRIMARY="BTC-EUR"
INVALID_KINDS={
    "connect","disconnect","duplicate_nonce","stale_nonce","forward_nonce_gap",
    "nonce_gap","resync_failed","resync_exception","ws_error","run_exception",
    "full_resubscribe_required",
}

# Operational stop margin locked before inspecting v1.0.6 market outcomes.
MIN_TOTAL_VALID_SECONDS=7200.0      # 2h; formal M1A timing minimum implies ~75m total
MIN_EST_HOLDOUT_SECONDS=2400.0      # 40m, vs formal 30m holdout valid observation
MIN_EST_HOLDOUT_FULL_60S_BLOCKS=12  # formal minimum is 10 blocks

def load_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for n,line in enumerate(f,1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except Exception as e:
                raise RuntimeError(f"{path}:{n}: invalid JSON: {e}")

def last_jsonl(path: Path):
    if not path.exists() or path.stat().st_size==0:
        return None
    with path.open("rb") as f:
        pos=f.seek(0,os.SEEK_END)
        buf=b""
        while pos>0:
            step=min(65536,pos)
            pos-=step
            f.seek(pos)
            buf=f.read(step)+buf
            lines=[x for x in buf.splitlines() if x.strip()]
            if lines:
                try:
                    return json.loads(lines[-1])
                except Exception:
                    if pos==0:
                        raise
    return None

def applicable(x, market):
    return x.get("market") in (None,market)

def build_intervals(root: Path, market: str):
    sessions=list(load_jsonl(root/"sessions.jsonl"))
    if not sessions:
        raise RuntimeError("sessions.jsonl is empty")

    for x in sessions:
        if x.get("collector_version")!=M0_VERSION:
            raise RuntimeError(f"unexpected collector_version {x.get('collector_version')!r}")
        if not x.get("boot_id"):
            raise RuntimeError("session record missing boot_id")
        if x.get("mono_ns") is None or x.get("utc_ns") is None:
            raise RuntimeError("session record missing monotonic/UTC timestamp")

    sessions.sort(key=lambda x:(int(x["utc_ns"]),int(x["mono_ns"])))
    intervals=[]
    open_start=None
    open_boot=None
    kinds=Counter()

    def close(end_mono, end_boot, reason):
        nonlocal open_start,open_boot
        if open_start is None:
            return
        if end_boot!=open_boot:
            open_start=None;open_boot=None
            return
        end=int(end_mono)
        if end>open_start:
            intervals.append({
                "boot_id":open_boot,
                "start_mono_ns":open_start,
                "end_mono_ns":end,
                "seconds":(end-open_start)/1e9,
                "end_reason":reason,
            })
        open_start=None;open_boot=None

    for x in sessions:
        k=x.get("kind")
        kinds[k]+=1
        boot=x["boot_id"]; mono=int(x["mono_ns"])

        if k=="book_valid" and x.get("market")==market:
            if open_start is None:
                open_start=mono;open_boot=boot
            elif boot!=open_boot:
                open_start=mono;open_boot=boot
            continue

        if k in INVALID_KINDS and applicable(x,market):
            close(mono,boot,k)

    # Close an open interval at latest raw receive watermark, without scanning
    # the raw dataset or inspecting any market values.
    tail=last_jsonl(root/"raw_events.jsonl")
    if open_start is not None and tail is not None:
        if tail.get("collector_version")!=M0_VERSION or tail.get("boot_id")!=open_boot:
            close(open_start,open_boot,"boot_changed_or_tail_mismatch")
        elif tail.get("recv_mono_ns") is not None:
            close(int(tail["recv_mono_ns"]),open_boot,"latest_raw_receive")

    return intervals,kinds

def split_intervals_by_valid_time(intervals, discovery_fraction=.60):
    total=sum(x["seconds"] for x in intervals)
    cut=total*discovery_fraction
    acc=0.0
    disc=[]; hold=[]
    for x in intervals:
        s=x["seconds"]
        if acc+s<=cut:
            disc.append(dict(x))
        elif acc>=cut:
            hold.append(dict(x))
        else:
            left=cut-acc
            right=s-left
            if left>0:
                a=dict(x);a["seconds"]=left;disc.append(a)
            if right>0:
                b=dict(x);b["seconds"]=right;hold.append(b)
        acc+=s
    return disc,hold

def full_blocks(intervals, block_seconds=60.0):
    return sum(int(x["seconds"]//block_seconds) for x in intervals)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True)
    ap.add_argument("--market",default=PRIMARY)
    a=ap.parse_args()
    root=Path(a.input).resolve()

    for name in ("sessions.jsonl","raw_events.jsonl","book_checkpoints.jsonl"):
        if not (root/name).exists():
            raise SystemExit(f"M0 READINESS FAIL: missing {name}")

    intervals,kinds=build_intervals(root,a.market)
    disc,hold=split_intervals_by_valid_time(intervals)
    total=sum(x["seconds"] for x in intervals)
    disc_s=sum(x["seconds"] for x in disc)
    hold_s=sum(x["seconds"] for x in hold)
    hold_blocks=full_blocks(hold)

    checks={
        "total_valid_seconds_margin": total>=MIN_TOTAL_VALID_SECONDS,
        "estimated_holdout_valid_seconds_margin": hold_s>=MIN_EST_HOLDOUT_SECONDS,
        "estimated_holdout_full_60s_blocks_margin": hold_blocks>=MIN_EST_HOLDOUT_FULL_60S_BLOCKS,
    }
    out={
        "schema":"m0-readiness-v1",
        "outcome_blind":True,
        "collector_version_required":M0_VERSION,
        "market":a.market,
        "operational_thresholds":{
            "total_valid_seconds":MIN_TOTAL_VALID_SECONDS,
            "estimated_holdout_valid_seconds":MIN_EST_HOLDOUT_SECONDS,
            "estimated_holdout_full_60s_blocks":MIN_EST_HOLDOUT_FULL_60S_BLOCKS,
        },
        "observed":{
            "valid_intervals":len(intervals),
            "total_valid_seconds":round(total,3),
            "estimated_discovery_valid_seconds":round(disc_s,3),
            "estimated_holdout_valid_seconds":round(hold_s,3),
            "estimated_holdout_full_60s_blocks":hold_blocks,
            "longest_valid_interval_seconds":round(max((x["seconds"] for x in intervals),default=0.0),3),
            "session_event_counts":dict(sorted(kinds.items())),
        },
        "checks":checks,
        "ready_for_freeze_estimate":all(checks.values()),
        "note":"Operational collection-stop estimate only; M1A formal minimum-data gate is evaluated only after immutable FREEZE_002.",
    }
    print(json.dumps(out,indent=2,sort_keys=True))

if __name__=="__main__":
    main()
