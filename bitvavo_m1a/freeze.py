#!/usr/bin/env python3
import argparse, hashlib, json, time
from pathlib import Path

FILES=("raw_events.jsonl","sessions.jsonl","book_checkpoints.jsonl")

def canon(x): return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def sha256(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser(description='Freeze an immutable M1A dataset at a pre-analysis UTC cutoff.')
    ap.add_argument('--source',required=True); ap.add_argument('--output',required=True)
    ap.add_argument('--cutoff-utc-ns',type=int,default=None); ap.add_argument('--m0-version',default='1.0.5')
    a=ap.parse_args(); src=Path(a.source).resolve(); out=Path(a.output).resolve()
    cutoff=a.cutoff_utc_ns or time.time_ns()
    if out.exists() and any(out.iterdir()): raise SystemExit(f'Refusing non-empty output: {out}')
    out.mkdir(parents=True,exist_ok=True)
    counts={}; hashes={}
    for name in FILES:
        ip=src/name; op=out/name
        if not ip.exists(): raise SystemExit(f'Missing required M0 file: {ip}')
        n=0
        with ip.open(encoding='utf-8') as fi, op.open('w',encoding='utf-8',newline='\n') as fo:
            for lineno,line in enumerate(fi,1):
                try: x=json.loads(line)
                except Exception as e: raise SystemExit(f'Invalid JSON {ip}:{lineno}: {e}')
                ts=x.get('recv_utc_ns',x.get('utc_ns'))
                if ts is None: raise SystemExit(f'Missing receive UTC timestamp {ip}:{lineno}')
                if int(ts) < cutoff:
                    fo.write(canon(x)+'\n'); n+=1
        counts[name]=n; hashes[name]=sha256(op)
    manifest={
      'schema':'m1a-freeze-v1','research_cutoff_utc_ns':cutoff,
      'research_cutoff_utc':time.strftime('%Y-%m-%dT%H:%M:%S',time.gmtime(cutoff//1_000_000_000))+f'.{cutoff%1_000_000_000:09d}Z',
      'source':str(src),'files':{n:{'records':counts[n],'sha256':hashes[n]} for n in FILES},
      'freeze_tool_version':'1.0.0','m0_version':a.m0_version
    }
    (out/'freeze_manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps(manifest,indent=2))
if __name__=='__main__': main()
