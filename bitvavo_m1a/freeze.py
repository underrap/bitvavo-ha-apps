#!/usr/bin/env python3
import argparse, hashlib, json, time
from pathlib import Path

FILES=("raw_events.jsonl","sessions.jsonl","book_checkpoints.jsonl")
FREEZE_ID="M1A_FREEZE_001"
M0_VERSION="1.0.5"
CAPABILITY="persisted_reconstructed_book_checkpoints_v1"

def canon(x): return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def sha256(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def checkpoint_capability(path):
    counts={}
    valid_primary=0
    for lineno,x in enumerate(load_jsonl(path),1):
        m=x.get("market","?")
        counts[m]=counts.get(m,0)+1
        if m=="BTC-EUR":
            required=("mono_ns","utc_ns","nonce","bids","asks")
            if not all(k in x for k in required):
                raise SystemExit(f'Checkpoint capability failure {path}:{lineno}: missing required fields')
            if not x["bids"] or not x["asks"]:
                raise SystemExit(f'Checkpoint capability failure {path}:{lineno}: empty reconstructed book')
            valid_primary+=1
    if valid_primary<1:
        raise SystemExit('Checkpoint capability failure: no valid BTC-EUR persisted reconstructed-book checkpoint')
    return counts

def load_jsonl(path):
    with path.open(encoding='utf-8') as f:
        for lineno,line in enumerate(f,1):
            try: yield json.loads(line)
            except Exception as e: raise SystemExit(f'Invalid JSON {path}:{lineno}: {e}')

def main():
    ap=argparse.ArgumentParser(description='Freeze an immutable M1A dataset at a pre-analysis UTC cutoff.')
    ap.add_argument('--source',required=True); ap.add_argument('--output',required=True)
    ap.add_argument('--cutoff-utc-ns',type=int,default=None); ap.add_argument('--m0-version',required=True)
    a=ap.parse_args(); src=Path(a.source).resolve(); out=Path(a.output).resolve()
    if a.m0_version != M0_VERSION:
        raise SystemExit(f'Refusing M0 version {a.m0_version!r}; exact required version is {M0_VERSION}')
    cutoff=a.cutoff_utc_ns or time.time_ns()
    if out.exists() and any(out.iterdir()): raise SystemExit(f'Refusing non-empty output: {out}')
    for name in FILES:
        if not (src/name).exists(): raise SystemExit(f'Missing required M0 file: {src/name}')
    checkpoint_counts=checkpoint_capability(src/"book_checkpoints.jsonl")
    out.mkdir(parents=True,exist_ok=True)
    counts={}; hashes={}; bounds={}
    for name in FILES:
        ip=src/name; op=out/name
        n=0; first_ts=None; last_ts=None
        with ip.open(encoding='utf-8') as fi, op.open('w',encoding='utf-8',newline='\n') as fo:
            for lineno,line in enumerate(fi,1):
                try: x=json.loads(line)
                except Exception as e: raise SystemExit(f'Invalid JSON {ip}:{lineno}: {e}')
                ts=x.get('recv_utc_ns',x.get('utc_ns'))
                if ts is None: raise SystemExit(f'Missing receive UTC timestamp {ip}:{lineno}')
                if int(ts) < cutoff:
                    fo.write(canon(x)+'\n'); n+=1
                    first_ts=int(ts) if first_ts is None else min(first_ts,int(ts)); last_ts=int(ts) if last_ts is None else max(last_ts,int(ts))
        counts[name]=n; hashes[name]=sha256(op); bounds[name]=(first_ts,last_ts)
    manifest={
      'schema':'m1a-freeze-v1','freeze_id':FREEZE_ID,'research_cutoff_utc_ns':cutoff,
      'research_cutoff_utc':time.strftime('%Y-%m-%dT%H:%M:%S',time.gmtime(cutoff//1_000_000_000))+f'.{cutoff%1_000_000_000:09d}Z',
      'source':str(src),'files':{n:{'records':counts[n],'sha256':hashes[n],'first_utc_ns':bounds[n][0],'last_utc_ns':bounds[n][1]} for n in FILES},
      'freeze_tool_version':'1.1.0','m0_version':a.m0_version,
      'm0_capability':CAPABILITY,'checkpoint_capability_verified':True,'checkpoint_counts':checkpoint_counts
    }
    (out/'freeze_manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps(manifest,indent=2))
if __name__=='__main__': main()
