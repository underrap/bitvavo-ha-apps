#!/usr/bin/env python3
"""Pre-run provenance gate for M1A-PREREG-v1.3. Does not analyze market data."""
import argparse, hashlib, json, re, sys
from datetime import datetime, timezone
from pathlib import Path

PROTOCOL="M1A-PREREG-v1.3"
CONTENT_PROTOCOL="M1A-PREREG-v1.2"
EXECUTOR_VERSION="1.2.0"
FREEZE_ID="M1A_FREEZE_001"
M0_VERSION="1.0.5"
REQUIRED=("raw_events.jsonl","sessions.jsonl","book_checkpoints.jsonl")
SHA_RE=re.compile(r"^[0-9a-f]{40}$")

def sha256(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def iso_ns(ns):
    ns=int(ns)
    sec,rem=divmod(ns,1_000_000_000)
    dt=datetime.fromtimestamp(sec,tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")+f".{rem:09d}Z"

def fail(msg):
    print("M1A PRE-RUN GATE: FAIL — "+msg,file=sys.stderr)
    raise SystemExit(64)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--freeze",required=True)
    ap.add_argument("--provenance",required=True)
    ap.add_argument("--execution-commit",required=True)
    a=ap.parse_args()

    freeze=Path(a.freeze).resolve()
    prov_path=Path(a.provenance).resolve()
    commit=a.execution_commit.strip().lower()
    if not SHA_RE.fullmatch(commit):
        fail("execution commit must be an exact 40-character lowercase Git SHA")

    if not prov_path.exists():
        fail(f"missing provenance record: {prov_path}")
    if not freeze.is_dir():
        fail(f"missing freeze directory: {freeze}")

    prov=json.loads(prov_path.read_text(encoding="utf-8"))
    required_exact={
        "protocol":PROTOCOL,
        "content_protocol":CONTENT_PROTOCOL,
        "executor_version":EXECUTOR_VERSION,
        "freeze_id":FREEZE_ID,
        "m0_version":M0_VERSION,
        "protocol_conformance_tests":"PASS",
    }
    for k,v in required_exact.items():
        if prov.get(k)!=v:
            fail(f"{k}={prov.get(k)!r}; expected {v!r}")
    if prov.get("execution_commit_sha")!=commit:
        fail("execution_commit_sha does not match the pinned runtime commit")

    manifest_path=freeze/"freeze_manifest.json"
    if not manifest_path.exists():
        fail("freeze_manifest.json missing")
    manifest_sha=sha256(manifest_path)
    if prov.get("manifest_sha256")!=manifest_sha:
        fail("manifest SHA-256 mismatch")

    mf=json.loads(manifest_path.read_text(encoding="utf-8"))
    if mf.get("freeze_id")!=FREEZE_ID:
        fail(f"freeze manifest freeze_id={mf.get('freeze_id')!r}; expected {FREEZE_ID!r}")
    if mf.get("m0_version")!=M0_VERSION:
        fail(f"freeze manifest m0_version={mf.get('m0_version')!r}; expected {M0_VERSION!r}")
    if mf.get("m0_capability")!="persisted_reconstructed_book_checkpoints_v1" or mf.get("checkpoint_capability_verified") is not True:
        fail("freeze manifest does not prove required persisted reconstructed-book checkpoint capability")
    if mf.get("research_cutoff_utc")!=prov.get("research_cutoff_utc"):
        fail("research_cutoff_utc mismatch between provenance and freeze manifest")

    source_paths=prov.get("raw_source_paths")
    source_hashes=prov.get("raw_source_sha256")
    if not isinstance(source_paths,dict) or not isinstance(source_hashes,dict):
        fail("raw_source_paths/raw_source_sha256 must be filename-keyed objects")

    first=[]
    last=[]
    for name in REQUIRED:
        p=freeze/name
        meta=mf.get("files",{}).get(name)
        if not p.exists() or not meta:
            fail(f"required frozen file/manifest entry missing: {name}")
        actual=sha256(p)
        if meta.get("sha256")!=actual:
            fail(f"freeze manifest hash mismatch: {name}")
        if source_hashes.get(name)!=actual:
            fail(f"provenance raw_source_sha256 mismatch: {name}")
        if not source_paths.get(name):
            fail(f"provenance raw_source_paths missing: {name}")
        if meta.get("first_utc_ns") is not None:
            first.append(int(meta["first_utc_ns"]))
        if meta.get("last_utc_ns") is not None:
            last.append(int(meta["last_utc_ns"]))

    if not first or not last:
        fail("freeze manifest has no first/last event bounds")
    first_iso=iso_ns(min(first))
    last_iso=iso_ns(max(last))
    if prov.get("first_event_utc")!=first_iso:
        fail(f"first_event_utc mismatch; expected {first_iso}")
    if prov.get("last_event_utc")!=last_iso:
        fail(f"last_event_utc mismatch; expected {last_iso}")

    print(json.dumps({
        "gate":"PASS",
        "protocol":PROTOCOL,
        "executor_version":EXECUTOR_VERSION,
        "execution_commit_sha":commit,
        "freeze_id":FREEZE_ID,
        "research_cutoff_utc":mf.get("research_cutoff_utc"),
        "manifest_sha256":manifest_sha,
        "first_event_utc":first_iso,
        "last_event_utc":last_iso
    },indent=2))

if __name__=="__main__":
    main()
