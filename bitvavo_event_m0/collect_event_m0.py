#!/usr/bin/env python3
"""Bitvavo M0 public event-level research collector. NO AUTH, NO ORDERS."""
import argparse, json, os, signal, threading, time
from collections import defaultdict
from pathlib import Path
import requests, websocket

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
        with path.open("a",encoding="utf-8",buffering=1) as f: f.write(canon(obj)+"\n")

class Collector:
    def __init__(self,root):
        self.root=root; root.mkdir(parents=True,exist_ok=True)
        self.raw=root/"raw_events.jsonl"; self.sessions=root/"sessions.jsonl"
        self.books={m:{"valid":False,"nonce":None,"bids":{},"asks":{},"buffer":[],"syncing":False} for m in MARKETS}
        self.counts=defaultdict(int); self.session=0; self.ws=None\n        self.book_locks={m:threading.RLock() for m in MARKETS}
    def meta(self,kind,**kw):
        append(self.sessions,{"kind":kind,"utc_ns":utc_ns(),"mono_ns":mono_ns(),"session":self.session,**kw})
    def record(self,msg):
        rec={"recv_utc_ns":utc_ns(),"recv_mono_ns":mono_ns(),"session":self.session,"raw":msg}
        append(self.raw,rec)
        return rec
    def on_open(self,ws):
        self.session+=1; self.meta("connect")
        for m in MARKETS:
            b=self.books[m]; b.update(valid=False,nonce=None,bids={},asks={},buffer=[],syncing=False)
        ws.send(canon({"action":"subscribe","channels":[
            {"name":"trades","markets":list(MARKETS)},
            {"name":"book","markets":list(MARKETS)}]}))
    def on_message(self,ws,text):
        try: msg=json.loads(text)
        except Exception as e:
            self.meta("decode_error",error=repr(e),sample=text[:500]); return
        self.record(msg)
        ev=msg.get("event")
        if ev=="trade":
            self.counts["trade_"+msg.get("market","?")]+=1; return
        if ev!="book" or "market" not in msg or "nonce" not in msg: return
        m=msg["market"]; b=self.books.get(m)
        if b is None:return
        self.counts["book_"+m]+=1
        n=int(msg["nonce"])
        launch=False
        with self.book_locks[m]:
            if not b["valid"]:
                b["buffer"].append(msg)
                if not b["syncing"]:
                    b["syncing"]=True; launch=True
            else:
                expected=b["nonce"]+1
                if n!=expected:
                    self.meta("nonce_gap",market=m,expected=expected,received=n)
                    b["valid"]=False; b["nonce"]=None; b["bids"]={}; b["asks"]={}; b["buffer"]=[msg]
                    if not b["syncing"]:
                        b["syncing"]=True; launch=True
                else:
                    self.apply(b,msg)
        if launch:
            threading.Thread(target=self.sync_book,args=(m,),daemon=True).start()
    def apply(self,b,msg):
        for side in ("bids","asks"):
            d=b[side]
            for price,size in msg.get(side,[]):
                if size=="0": d.pop(price,None)
                else: d[price]=size
        b["nonce"]=int(msg["nonce"])
    def sync_book(self,m):
        b=self.books[m]
        try:
            for attempt in range(12):
                if stop.is_set(): return
                # Need at least one buffered WS update before accepting a snapshot.
                with self.book_locks[m]:
                    buffered=list(b["buffer"])
                if not buffered: time.sleep(.05); continue
                first=min(int(x["nonce"]) for x in buffered)
                t0=utc_ns()
                r=requests.get(f"{REST}/{m}/book",params={"depth":1000},timeout=10)
                t1=utc_ns(); r.raise_for_status(); snap=r.json(); sn=int(snap["nonce"])
                self.meta("snapshot",market=m,nonce=sn,http_elapsed_ns=t1-t0)
                # Official procedure: snapshot must be > initial buffered update.
                if sn<=first:
                    time.sleep(.05); continue
                with self.book_locks[m]:
                    pending=sorted((x for x in b["buffer"] if int(x["nonce"])>sn),key=lambda x:int(x["nonce"]))
                bids={p:s for p,s in snap.get("bids",[]) if s!="0"}
                asks={p:s for p,s in snap.get("asks",[]) if s!="0"}
                candidate={"valid":True,"nonce":sn,"bids":bids,"asks":asks}
                ok=True
                for x in pending:
                    if int(x["nonce"])!=candidate["nonce"]+1:
                        ok=False; break
                    self.apply(candidate,x)
                if not ok:
                    self.meta("resync_retry",market=m,reason="buffer_gap",snapshot_nonce=sn)
                    time.sleep(.05); continue
                # Atomically consume all updates that arrived during snapshot/replay.
                with self.book_locks[m]:
                    newer=sorted((x for x in b["buffer"] if int(x["nonce"])>candidate["nonce"]),key=lambda x:int(x["nonce"]))
                    for x in newer:
                        if int(x["nonce"])!=candidate["nonce"]+1:
                            ok=False; break
                        self.apply(candidate,x)
                    if ok:
                        b["bids"]=candidate["bids"]; b["asks"]=candidate["asks"]; b["nonce"]=candidate["nonce"]
                        b["buffer"]=[]; b["valid"]=True
                        levels=(len(b["bids"]),len(b["asks"]),b["nonce"])
                if not ok:
                    self.meta("resync_retry",market=m,reason="late_buffer_gap",snapshot_nonce=sn)
                    time.sleep(.05); continue
                self.meta("book_valid",market=m,nonce=levels[2],bid_levels=levels[0],ask_levels=levels[1])
                return
            self.meta("resync_failed",market=m)
        except Exception as e:
            self.meta("resync_exception",market=m,error=repr(e))
        finally:
            b["syncing"]=False
    def on_error(self,ws,error): self.meta("ws_error",error=repr(error))
    def on_close(self,ws,code,reason):
        for b in self.books.values(): b["valid"]=False
        self.meta("disconnect",code=code,reason=reason)
    def run(self):
        backoff=1
        while not stop.is_set():
            try:
                self.ws=websocket.WebSocketApp(WS,on_open=self.on_open,on_message=self.on_message,
                    on_error=self.on_error,on_close=self.on_close)
                self.ws.run_forever(ping_interval=20,ping_timeout=10)
            except Exception as e: self.meta("run_exception",error=repr(e))
            if stop.is_set(): break
            self.meta("reconnect_wait",seconds=backoff); stop.wait(backoff); backoff=min(30,backoff*2)
        self.meta("stop",counts=dict(self.counts))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output",required=True); a=ap.parse_args()
    root=Path(a.output).resolve()
    c=Collector(root)
    def halt(*_):
        stop.set()
        if c.ws:
            try:c.ws.close()
            except:pass
    signal.signal(signal.SIGTERM,halt); signal.signal(signal.SIGINT,halt)
    print("M0 public event collector; NO API key; NO orders.")
    print("Markets:",", ".join(MARKETS)); print("Output:",root)
    c.run()

if __name__=="__main__": main()
