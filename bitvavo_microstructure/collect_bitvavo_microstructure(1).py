#!/usr/bin/env python3
"""
Prospective Bitvavo BTC/EUR vs BTC/USDC microstructure collector.

Research-only:
- public endpoints only; no API key
- no orders, balances, database or LIVE state
- paired REST order-book snapshots every 60s
- depth=100
- public trades polled every 5 minutes
- raw JSONL output, append-only
- resumable across restarts
- bounded retry/backoff and failure logging
- SHA-256 manifest written on clean exit / completion

Run:
  py -3 collect_bitvavo_microstructure.py --output bitvavo_microstructure_7d

Stop safely with Ctrl+C; rerun the same command to resume until 7 elapsed days
from the first successful paired snapshot.
"""
from __future__ import annotations
import argparse, hashlib, json, random, signal, sys, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import requests

API = "https://api.bitvavo.com/v2"
MARKETS = ("BTC-EUR", "BTC-USDC")
DEPTH = 100
SNAPSHOT_SECONDS = 60
TRADES_SECONDS = 300
DURATION_SECONDS = 7 * 24 * 3600
TIMEOUT = 20
MAX_RETRIES = 6
USER_AGENT = "Bitvavo-vNext-Microstructure-Research/1.0"

stop_requested = False

def now_ms(): return int(time.time() * 1000)
def iso_now(): return datetime.now(timezone.utc).isoformat()

def canonical(o: Any) -> str:
    return json.dumps(o, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()

def append_jsonl(path: Path, obj: Any):
    with path.open("a", encoding="utf-8", buffering=1) as f:
        f.write(canonical(obj) + "\n")

def request_json(session, path, params, weight):
    last = None
    for attempt in range(MAX_RETRIES):
        local_send = now_ms()
        try:
            r = session.get(API + path, params=params, timeout=TIMEOUT)
            local_recv = now_ms()
            if r.status_code == 429 or 500 <= r.status_code < 600:
                ra = r.headers.get("Retry-After")
                try: wait = float(ra) if ra else min(30.0, 1.5**attempt)
                except ValueError: wait = min(30.0, 1.5**attempt)
                time.sleep(wait + random.uniform(.05,.25)); last = f"HTTP {r.status_code}"; continue
            if 400 <= r.status_code < 500:
                raise RuntimeError(f"Permanent HTTP {r.status_code}: {r.text[:500]}")
            r.raise_for_status()
            return {
                "ok": True, "local_send_ms": local_send, "local_recv_ms": local_recv,
                "latency_ms": local_recv-local_send,
                "ratelimit_remaining": r.headers.get("bitvavo-ratelimit-remaining"),
                "ratelimit_resetat": r.headers.get("bitvavo-ratelimit-resetat"),
                "response": r.json(), "weight": weight,
            }
        except (requests.RequestException, ValueError, RuntimeError) as e:
            last = repr(e)
            if attempt < MAX_RETRIES-1:
                time.sleep(min(30.0, 1.5**attempt)+random.uniform(.05,.25))
    return {"ok": False, "local_send_ms": now_ms(), "error": last, "weight": weight}

def get_book(session, market):
    return request_json(session, f"/{market}/book", {"depth": DEPTH}, 1)

def get_trades(session, market, start_ms, end_ms):
    # A 5-minute interval should normally stay well below 1000. If it hits 1000,
    # record the truncation risk explicitly rather than pretending completeness.
    x = request_json(session, f"/{market}/trades",
                     {"start": start_ms, "end": end_ms, "limit": 1000}, 5)
    if x.get("ok"):
        data = x["response"]
        x["count"] = len(data) if isinstance(data, list) else None
        x["possible_truncation"] = isinstance(data, list) and len(data) >= 1000
    return x

def read_state(path):
    if not path.exists(): return {}
    return json.loads(path.read_text(encoding="utf-8"))

def write_state(path, state):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(canonical(state), encoding="utf-8")
    tmp.replace(path)

def on_signal(sig, frame):
    global stop_requested
    stop_requested = True

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output", default="bitvavo_microstructure_7d")
    p.add_argument("--days", type=float, default=7.0)
    args=p.parse_args()
    root=Path(args.output).resolve(); root.mkdir(parents=True, exist_ok=True)
    books=root/"paired_books.jsonl"; trades=root/"trade_windows.jsonl"
    failures=root/"failures.jsonl"; statep=root/"state.json"; manifestp=root/"manifest.json"

    signal.signal(signal.SIGINT,on_signal)
    if hasattr(signal,"SIGTERM"): signal.signal(signal.SIGTERM,on_signal)

    s=requests.Session()
    s.headers.update({"Accept":"application/json","User-Agent":USER_AGENT})

    state=read_state(statep)
    state.setdefault("version",1)
    state.setdefault("created_at",iso_now())
    state.setdefault("first_pair_ms",None)
    state.setdefault("pairs_attempted",0)
    state.setdefault("pairs_both_ok",0)
    state.setdefault("last_trade_end_ms",{m:None for m in MARKETS})

    duration_ms=int(args.days*86400*1000)
    next_book=time.monotonic()
    next_trades=time.monotonic()

    print("Public research collector; NO API key; NO orders.")
    print("Markets:", ", ".join(MARKETS), "| depth:",DEPTH)
    print("Output :",root)
    print("Stop safely with Ctrl+C; rerun same command to resume.")

    while not stop_requested:
        wall=now_ms()
        if state["first_pair_ms"] is not None and wall-state["first_pair_ms"] >= duration_ms:
            break

        if time.monotonic() >= next_book:
            pair_id=f"{wall}-{state['pairs_attempted']+1}"
            pair={"schema":1,"pair_id":pair_id,"collector_start_ms":wall,
                  "collector_start_utc":datetime.fromtimestamp(wall/1000,timezone.utc).isoformat(),
                  "depth":DEPTH,"books":{}}
            # Sequential requests; local send/recv + exchange timestamp quantify pairing skew.
            for m in MARKETS:
                pair["books"][m]=get_book(s,m)
            pair["collector_end_ms"]=now_ms()
            pair["pair_elapsed_ms"]=pair["collector_end_ms"]-wall
            state["pairs_attempted"]+=1
            both=all(pair["books"][m].get("ok") for m in MARKETS)
            pair["both_ok"]=both
            if both:
                state["pairs_both_ok"]+=1
                if state["first_pair_ms"] is None: state["first_pair_ms"]=wall
            else:
                append_jsonl(failures,{"type":"book_pair","at_ms":now_ms(),"pair_id":pair_id,
                                      "errors":{m:pair["books"][m].get("error") for m in MARKETS if not pair["books"][m].get("ok")}})
            append_jsonl(books,pair)
            write_state(statep,state)
            next_book += SNAPSHOT_SECONDS
            if next_book < time.monotonic()-SNAPSHOT_SECONDS: next_book=time.monotonic()+SNAPSHOT_SECONDS

        if time.monotonic() >= next_trades:
            end=now_ms()
            for m in MARKETS:
                prev=state["last_trade_end_ms"].get(m)
                start=prev if prev is not None else max(0,end-TRADES_SECONDS*1000)
                result=get_trades(s,m,start,end)
                rec={"schema":1,"market":m,"window_start_ms":start,"window_end_ms":end,
                     "collected_at_ms":now_ms(),"request":result}
                append_jsonl(trades,rec)
                if result.get("ok"):
                    # Overlapping boundary is intentionally retained; analysis deduplicates by trade id.
                    state["last_trade_end_ms"][m]=end
                    if result.get("possible_truncation"):
                        append_jsonl(failures,{"type":"trade_truncation_risk","at_ms":now_ms(),
                                              "market":m,"start_ms":start,"end_ms":end})
                else:
                    append_jsonl(failures,{"type":"trades","at_ms":now_ms(),"market":m,
                                          "start_ms":start,"end_ms":end,"error":result.get("error")})
            write_state(statep,state)
            next_trades += TRADES_SECONDS
            if next_trades < time.monotonic()-TRADES_SECONDS: next_trades=time.monotonic()+TRADES_SECONDS

        time.sleep(.2)

    state["stopped_at"]=iso_now()
    state["completed_duration"]=bool(state["first_pair_ms"] is not None and now_ms()-state["first_pair_ms"]>=duration_ms)
    write_state(statep,state)
    manifest={
        "version":1,"purpose":"prospective BTC-EUR vs BTC-USDC microstructure research",
        "public_only":True,"markets":list(MARKETS),"book_depth":DEPTH,
        "snapshot_interval_seconds":SNAPSHOT_SECONDS,"trade_poll_seconds":TRADES_SECONDS,
        "requested_days":args.days,"state":state,
        "files":{}
    }
    for pth in (books,trades,failures,statep):
        if pth.exists():
            manifest["files"][pth.name]={"bytes":pth.stat().st_size,"sha256":sha256_file(pth)}
    manifestp.write_text(canonical(manifest),encoding="utf-8")
    print("\nSTOPPED" if stop_requested else "\nDONE")
    print("Paired snapshots:",state["pairs_both_ok"],"/",state["pairs_attempted"])
    print("Manifest:",manifestp)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
