import hashlib,json,subprocess,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
BASE=Path(__file__).parent

def sha(p):
 h=hashlib.sha256();h.update(p.read_bytes());return h.hexdigest()

def iso_ns(ns):
 sec,rem=divmod(ns,1_000_000_000)
 return datetime.fromtimestamp(sec,tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")+f".{rem:09d}Z"

with tempfile.TemporaryDirectory() as d:
 root=Path(d)
 freeze=root/"frozen";freeze.mkdir()
 vals={
  "raw_events.jsonl":[{"recv_utc_ns":1000000000,"recv_mono_ns":1,"raw":{}}],
  "sessions.jsonl":[{"utc_ns":1100000000,"mono_ns":2,"kind":"book_valid"}],
  "book_checkpoints.jsonl":[{"utc_ns":1200000000,"mono_ns":3,"market":"BTC-EUR","nonce":1,"bids":[],"asks":[]}]
 }
 meta={}
 for name,rows in vals.items():
  p=freeze/name;p.write_text("".join(json.dumps(x)+"\n" for x in rows))
  ts=[x.get("recv_utc_ns",x.get("utc_ns")) for x in rows]
  meta[name]={"records":len(rows),"sha256":sha(p),"first_utc_ns":min(ts),"last_utc_ns":max(ts)}
 mf={"schema":"m1a-freeze-v1","research_cutoff_utc":"2026-10-03T00:00:00.000000000Z",
     "m0_version":"1.0.5","files":meta}
 (freeze/"freeze_manifest.json").write_text(json.dumps(mf,sort_keys=True))
 commit="1"*40
 prov={
  "protocol":"M1A-PREREG-v1.3","content_protocol":"M1A-PREREG-v1.2","executor_version":"1.2.0",
  "freeze_id":"M1A_FREEZE_001","m0_version":"1.0.5","protocol_conformance_tests":"PASS",
  "execution_commit_sha":commit,"research_cutoff_utc":mf["research_cutoff_utc"],
  "manifest_sha256":sha(freeze/"freeze_manifest.json"),
  "raw_source_paths":{n:f"/source/{n}" for n in vals},
  "raw_source_sha256":{n:meta[n]["sha256"] for n in vals},
  "first_event_utc":iso_ns(1000000000),"last_event_utc":iso_ns(1200000000)
 }
 pp=root/"execution_provenance.json";pp.write_text(json.dumps(prov))
 cmd=[sys.executable,str(BASE/"pre_run_gate.py"),"--freeze",str(freeze),"--provenance",str(pp),"--execution-commit",commit]
 cp=subprocess.run(cmd,text=True,capture_output=True)
 assert cp.returncode==0,cp.stderr+cp.stdout
 assert json.loads(cp.stdout)["gate"]=="PASS"

 bad=dict(prov);bad["execution_commit_sha"]="2"*40;pp.write_text(json.dumps(bad))
 cp=subprocess.run(cmd,text=True,capture_output=True)
 assert cp.returncode!=0
 assert "execution_commit_sha" in cp.stderr
 print("M1A pre-run provenance gate PASS")
