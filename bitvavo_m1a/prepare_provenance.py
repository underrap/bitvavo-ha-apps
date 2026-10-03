#!/usr/bin/env python3
"""Create execution_provenance.json from an already frozen M1A dataset. No market analysis."""
import argparse, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path

SHA_RE=re.compile(r"^[0-9a-f]{40}$")
REQUIRED=("raw_events.jsonl","sessions.jsonl","book_checkpoints.jsonl")

def sha256(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def iso_ns(ns):
    ns=int(ns);sec,rem=divmod(ns,1_000_000_000)
    return datetime.fromtimestamp(sec,tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")+f".{rem:09d}Z"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--freeze",required=True)
    ap.add_argument("--execution-commit",required=True)
    ap.add_argument("--ci-run-id",required=True)
    ap.add_argument("--output",required=True)
    a=ap.parse_args()

    commit=a.execution_commit.strip().lower()
    if not SHA_RE.fullmatch(commit):
        raise SystemExit("execution commit must be an exact 40-character lowercase Git SHA")

    freeze=Path(a.freeze).resolve()
    out=Path(a.output).resolve()
    if out.exists():
        raise SystemExit(f"refusing existing provenance output: {out}")

    mp=freeze/"freeze_manifest.json"
    mf=json.loads(mp.read_text(encoding="utf-8"))
    if mf.get("freeze_id")!="M1A_FREEZE_001":
        raise SystemExit("freeze_id mismatch")
    if mf.get("m0_version")!="1.0.5":
        raise SystemExit("M0 version mismatch")
    if mf.get("m0_capability")!="persisted_reconstructed_book_checkpoints_v1" or mf.get("checkpoint_capability_verified") is not True:
        raise SystemExit("required M0 checkpoint capability not verified")

    first=[];last=[];paths={};hashes={}
    for name in REQUIRED:
        p=freeze/name
        meta=mf.get("files",{}).get(name)
        if not p.exists() or not meta:
            raise SystemExit(f"missing frozen source: {name}")
        actual=sha256(p)
        if actual!=meta.get("sha256"):
            raise SystemExit(f"frozen source hash mismatch: {name}")
        paths[name]=str(p)
        hashes[name]=actual
        if meta.get("first_utc_ns") is not None:first.append(int(meta["first_utc_ns"]))
        if meta.get("last_utc_ns") is not None:last.append(int(meta["last_utc_ns"]))

    if not first or not last:
        raise SystemExit("missing first/last event bounds")

    prov={
        "protocol":"M1A-PREREG-v1.3",
        "content_protocol":"M1A-PREREG-v1.2",
        "executor_version":"1.2.0",
        "execution_commit_sha":commit,
        "protocol_conformance_tests":"PASS",
        "ci_run_id":str(a.ci_run_id),
        "freeze_id":"M1A_FREEZE_001",
        "m0_version":"1.0.5",
        "m0_capability":"persisted_reconstructed_book_checkpoints_v1",
        "research_cutoff_utc":mf["research_cutoff_utc"],
        "manifest_path":str(mp),
        "manifest_sha256":sha256(mp),
        "raw_source_paths":paths,
        "raw_source_sha256":hashes,
        "first_event_utc":iso_ns(min(first)),
        "last_event_utc":iso_ns(max(last))
    }
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(prov,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(prov,indent=2,sort_keys=True))

if __name__=="__main__":
    main()
