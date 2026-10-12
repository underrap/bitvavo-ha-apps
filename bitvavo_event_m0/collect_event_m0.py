#!/usr/bin/env python3
"""Bitvavo M0 public event-level research collector v1.0.6. NO AUTH, NO ORDERS.

Integrity goals:
- append-only raw public events with wall + monotonic receive clocks;
- restart/connection identity persisted on every record;
- persisted reconstructed-book checkpoints with a causal monotonic watermark;
- hard reconnect/resubscribe on any nonce discontinuity;
- no automatic trading or private API access.
"""
import argparse, json, signal, threading, time, uuid
from collections import defaultdict
from pathlib import Path
import requests, websocket

VERSION="1.0.6"
WS="wss://ws.bitvavo.com/v2/"
REST="https://api.bitvavo.com/v2"
MARKETS=("BTC-EUR","BTC-USDC")
stop=threading.Event()
io_lock=threading.Lock()

def utc_ns(): return time.time_ns()
def mono_ns(): return time.monotonic_ns()
def canon(x): return json.dumps(x,ensure_ascii=False,separators=(",",":"),sort_keys=True)
def append(path,obj):
    with io_lock:
        with path.open("a",encoding="utf-8",buffering=1) as f:
            f.write(canon(obj)+"\n")

def checkpoint_watermark(snapshot_recv_mono_ns, buffered_records, final_nonce):
    """Earliest monotonic time at which the checkpoint is causally usable.

    Include the REST snapshot receive time and every buffered book event whose
    nonce is incorporated into the checkpoint. An event received concurrently
    after this watermark but blocked on the book lock remains replayable.
    """
    covered=[int(snapshot_recv_mono_ns)]
    for rec in buffered_records:
        msg=rec.get("raw",{})
        if msg.get("nonce") is not None and int(msg["nonce"]) <= int(final_nonce):
            covered.append(int(rec["recv_mono_ns"]))
    return max(covered)

class Collector:
    def __init__(self,root):
        self.root=root; root.mkdir(parents=True,exist_ok=True)
        self.raw=root/"raw_events.jsonl"
        self.sessions=root/"sessions.jsonl"
        self.checkpoints=root/"book_checkpoints.jsonl"
        self.boot_id=str(uuid.uuid4())
        self.books={m:{"valid":False,"nonce":None,"bids":{},"asks":{},"buffer":[],"syncing":False} for m in MARKETS}
        self.counts=defaultdict(int)
        self.session=0
        self.ws=None
        self.book_locks={m:threading.RLock() for m in MARKETS}
        self.reconnect_lock=threading.Lock()
        self.reconnect_requested=False
        self.connected_mono_ns=None

    def meta(self,kind,**kw):
        append(self.sessions,{
            "kind":kind,"utc_ns":utc_ns(),"mono_ns":mono_ns(),
            "boot_id":self.boot_id,"session":self.session,"collector_version":VERSION,**kw
        })

    def record(self,msg):
        rec={
            "recv_utc_ns":utc_ns(),"recv_mono_ns":mono_ns(),
            "boot_id":self.boot_id,"session":self.session,
            "collector_version":VERSION,"raw":msg
        }
        append(self.raw,rec)
        return rec

    def subscribe_all(self,ws):
        ws.send(canon({"action":"subscribe","channels":[
            {"name":"trades","markets":list(MARKETS)},
            {"name":"book","markets":list(MARKETS)}
        ]}))

    def on_open(self,ws):
        self.session+=1
        self.connected_mono_ns=mono_ns()
        with self.reconnect_lock:
            self.reconnect_requested=False
        self.meta("connect")
        for m in MARKETS:
            with self.book_locks[m]:
                self.books[m].update(valid=False,nonce=None,bids={},asks={},buffer=[],syncing=False)
        self.subscribe_all(ws)

    def request_full_reconnect(self,market,reason,**kw):
        """Restart from Bitvavo order-book sync step 1 after any nonce discontinuity."""
        with self.reconnect_lock:
            if self.reconnect_requested:
                return
            self.reconnect_requested=True
        self.meta("full_resubscribe_required",market=market,reason=reason,**kw)
        for m in MARKETS:
            with self.book_locks[m]:
                self.books[m]["valid"]=False
                self.books[m]["nonce"]=None
                self.books[m]["bids"]={}
                self.books[m]["asks"]={}
                self.books[m]["buffer"]=[]
        if self.ws:
            try:
                self.ws.close()
            except Exception as e:
                self.meta("reconnect_close_exception",error=repr(e))

    def on_message(self,ws,text):
        try:
            msg=json.loads(text)
        except Exception as e:
            self.meta("decode_error",error=repr(e),sample=text[:500])
            return

        # Preserve immediate local receive time before any book-lock wait.
        rec=self.record(msg)
        ev=msg.get("event")
        if ev=="trade":
            self.counts["trade_"+msg.get("market","?")]+=1
            return
        if ev!="book" or "market" not in msg or "nonce" not in msg:
            return

        m=msg["market"]
        b=self.books.get(m)
        if b is None:
            return
        self.counts["book_"+m]+=1
        n=int(msg["nonce"])
        reconnect=None
        launch=False

        with self.book_locks[m]:
            if not b["valid"]:
                b["buffer"].append(rec)
                if not b["syncing"]:
                    b["syncing"]=True
                    launch=True
            else:
                current=int(b["nonce"])
                expected=current+1
                if n!=expected:
                    if n==current:
                        anomaly="duplicate_nonce"
                    elif n<current:
                        anomaly="stale_nonce"
                    else:
                        anomaly="forward_nonce_gap"
                    self.meta(anomaly,market=m,current=current,expected=expected,received=n)
                    reconnect=(anomaly,{"current":current,"expected":expected,"received":n})
                else:
                    self.apply(b,msg)

        if reconnect is not None:
            self.request_full_reconnect(m,reconnect[0],**reconnect[1])
            return
        if launch:
            threading.Thread(target=self.sync_book,args=(m,),daemon=True).start()

    def apply(self,b,msg):
        for side in ("bids","asks"):
            d=b[side]
            for price,size in msg.get(side,[]):
                if size=="0":
                    d.pop(price,None)
                else:
                    d[price]=size
        b["nonce"]=int(msg["nonce"])

    def sync_book(self,m):
        b=self.books[m]
        try:
            for attempt in range(12):
                if stop.is_set() or self.reconnect_requested:
                    return

                with self.book_locks[m]:
                    buffered=list(b["buffer"])
                if not buffered:
                    time.sleep(.05)
                    continue

                first=min(int(x["raw"]["nonce"]) for x in buffered)
                request_utc=utc_ns()
                request_mono=mono_ns()
                r=requests.get(f"{REST}/{m}/book",params={"depth":1000},timeout=10)
                snap_recv_mono=mono_ns()
                response_utc=utc_ns()
                r.raise_for_status()
                snap=r.json()
                sn=int(snap["nonce"])
                self.meta(
                    "snapshot",market=m,nonce=sn,
                    http_elapsed_ns=response_utc-request_utc,
                    http_elapsed_mono_ns=snap_recv_mono-request_mono
                )

                # Bitvavo sync procedure: snapshot must advance beyond the first
                # buffered update before it can anchor the local book.
                if sn<=first:
                    time.sleep(.05)
                    continue

                with self.book_locks[m]:
                    pending=sorted(
                        (x for x in b["buffer"] if int(x["raw"]["nonce"])>sn),
                        key=lambda x:int(x["raw"]["nonce"])
                    )
                bids={p:s for p,s in snap.get("bids",[]) if s!="0"}
                asks={p:s for p,s in snap.get("asks",[]) if s!="0"}
                candidate={"valid":True,"nonce":sn,"bids":bids,"asks":asks}

                ok=True
                for rec in pending:
                    x=rec["raw"]
                    if int(x["nonce"])!=int(candidate["nonce"])+1:
                        ok=False
                        break
                    self.apply(candidate,x)
                if not ok:
                    self.meta("resync_retry",market=m,reason="buffer_gap",snapshot_nonce=sn)
                    time.sleep(.05)
                    continue

                with self.book_locks[m]:
                    final_buffer=list(b["buffer"])
                    newer=sorted(
                        (x for x in final_buffer if int(x["raw"]["nonce"])>int(candidate["nonce"])),
                        key=lambda x:int(x["raw"]["nonce"])
                    )
                    for rec in newer:
                        x=rec["raw"]
                        if int(x["nonce"])!=int(candidate["nonce"])+1:
                            ok=False
                            break
                        self.apply(candidate,x)

                    if ok:
                        b["bids"]=candidate["bids"]
                        b["asks"]=candidate["asks"]
                        b["nonce"]=candidate["nonce"]
                        b["buffer"]=[]
                        b["valid"]=True
                        levels=(len(b["bids"]),len(b["asks"]),int(b["nonce"]))
                        covered_mono=checkpoint_watermark(
                            snap_recv_mono,final_buffer,int(b["nonce"])
                        )
                        checkpoint={
                            "kind":"book_checkpoint","market":m,
                            "boot_id":self.boot_id,"session":self.session,
                            "collector_version":VERSION,
                            # Causal replay anchor. Do not use checkpoint write time:
                            # a WS callback can have captured an event while blocked
                            # on this book lock.
                            "mono_ns":covered_mono,
                            "utc_ns":utc_ns(),
                            "nonce":int(b["nonce"]),
                            "covered_through_recv_mono_ns":covered_mono,
                            "snapshot_recv_mono_ns":snap_recv_mono,
                            "bids":sorted(b["bids"].items(),key=lambda x:float(x[0]),reverse=True),
                            "asks":sorted(b["asks"].items(),key=lambda x:float(x[0]))
                        }

                if not ok:
                    self.meta("resync_retry",market=m,reason="late_buffer_gap",snapshot_nonce=sn)
                    time.sleep(.05)
                    continue

                append(self.checkpoints,checkpoint)
                self.meta(
                    "book_valid",market=m,nonce=levels[2],
                    bid_levels=levels[0],ask_levels=levels[1],
                    checkpoint_nonce=levels[2],
                    checkpoint_covered_through_recv_mono_ns=covered_mono
                )
                return

            self.meta("resync_failed",market=m)
            self.request_full_reconnect(m,"resync_failed")
        except Exception as e:
            self.meta("resync_exception",market=m,error=repr(e))
            self.request_full_reconnect(m,"resync_exception",error=repr(e))
        finally:
            with self.book_locks[m]:
                b["syncing"]=False

    def on_error(self,ws,error):
        self.meta("ws_error",error=repr(error))

    def on_close(self,ws,code,reason):
        for m,b in self.books.items():
            with self.book_locks[m]:
                b["valid"]=False
        self.meta("disconnect",code=code,reason=reason)

    def run(self):
        backoff=1
        self.meta("collector_start",boot_id=self.boot_id)
        while not stop.is_set():
            started=mono_ns()
            try:
                self.ws=websocket.WebSocketApp(
                    WS,on_open=self.on_open,on_message=self.on_message,
                    on_error=self.on_error,on_close=self.on_close
                )
                self.ws.run_forever(ping_interval=20,ping_timeout=10)
            except Exception as e:
                self.meta("run_exception",error=repr(e))

            if stop.is_set():
                break

            lived_ns=mono_ns()-started
            # A genuinely healthy connection earns a short reconnect delay again.
            if lived_ns>=60_000_000_000:
                backoff=1
            self.meta("reconnect_wait",seconds=backoff)
            stop.wait(backoff)
            backoff=min(30,backoff*2)

        self.meta("stop",counts=dict(self.counts))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",required=True)
    a=ap.parse_args()
    root=Path(a.output).resolve()
    c=Collector(root)

    def halt(*_):
        stop.set()
        if c.ws:
            try:
                c.ws.close()
            except Exception:
                pass

    signal.signal(signal.SIGTERM,halt)
    signal.signal(signal.SIGINT,halt)
    print(f"M0 public event collector v{VERSION}; NO API key; NO orders.")
    print("Markets:",", ".join(MARKETS))
    print("Output:",root)
    c.run()

if __name__=="__main__":
    main()
