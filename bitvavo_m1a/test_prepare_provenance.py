import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
BASE=Path(__file__).parent

def sha(p):
 h=hashlib.sha256();h.update(p.read_bytes());return h.hexdigest()

with tempfile.TemporaryDirectory() as d:
 root=Path(d);freeze=root/"frozen";freeze.mkdir();out=root/"execution_provenance.json"
 rows={
  "raw_events.jsonl":[{"recv_utc_ns":1_000_000_000}],
  "sessions.jsonl":[{"utc_ns":1_100_000_000}],
  "book_checkpoints.jsonl":[{"utc_ns":1_200_000_000}]
 }
 meta={}
 for name,xs in rows.items():
  p=freeze/name;p.write_text("".join(json.dumps(x)+"\n" for x in xs))
  ts=[x.get("recv_utc_ns",x.get("utc_ns")) for x in xs]
  meta[name]={"sha256":sha(p),"records":len(xs),"first_utc_ns":min(ts),"last_utc_ns":max(ts)}
 mf={"schema":"m1a-freeze-v1","freeze_id":"M1A_FREEZE_001","m0_version":"1.0.5",
     "m0_capability":"persisted_reconstructed_book_checkpoints_v1","checkpoint_capability_verified":True,
     "research_cutoff_utc":"2026-10-03T12:00:00.000000000Z","files":meta}
 (freeze/"freeze_manifest.json").write_text(json.dumps(mf))
 commit="a"*40
 cp=subprocess.run([sys.executable,str(BASE/"prepare_provenance.py"),"--freeze",str(freeze),
                    "--execution-commit",commit,"--ci-run-id","12345","--output",str(out)],
                   text=True,capture_output=True)
 assert cp.returncode==0,cp.stderr+cp.stdout
 p=json.loads(out.read_text())
 assert p["execution_commit_sha"]==commit
 assert p["manifest_sha256"]==sha(freeze/"freeze_manifest.json")
 assert p["first_event_utc"]=="1970-01-01T00:00:01.000000000Z"
 assert p["last_event_utc"]=="1970-01-01T00:00:01.200000000Z"
 print("M1A provenance preparation PASS")
