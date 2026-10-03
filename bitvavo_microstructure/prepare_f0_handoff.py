#!/usr/bin/env python3
"""Prepare a completed F0 collector directory for handoff without analyzing market outcomes."""
from __future__ import annotations
import argparse, hashlib, json, zipfile
from pathlib import Path

REQUIRED=("paired_books.jsonl","trade_windows.jsonl","state.json","manifest.json")
OPTIONAL=("failures.jsonl",)

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def fail(msg: str):
    raise SystemExit("F0 HANDOFF: FAIL — "+msg)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True)
    ap.add_argument("--output",required=True)
    args=ap.parse_args()

    root=Path(args.input).resolve()
    out=Path(args.output).resolve()
    if not root.is_dir():
        fail(f"input directory not found: {root}")
    if out.exists():
        fail(f"refusing existing output: {out}")

    for name in REQUIRED:
        if not (root/name).exists():
            fail(f"missing required file: {name}")

    state=json.loads((root/"state.json").read_text(encoding="utf-8"))
    if state.get("completed_duration") is not True:
        fail("collector has not completed its requested duration")
    if state.get("first_pair_ms") is None or state.get("stopped_at") is None:
        fail("state is missing first_pair_ms/stopped_at")
    if int(state.get("pairs_both_ok",0))<=0:
        fail("state reports no successful paired snapshots")

    manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
    if manifest.get("public_only") is not True:
        fail("manifest public_only is not true")
    if manifest.get("book_depth")!=100:
        fail(f"unexpected book_depth: {manifest.get('book_depth')!r}")
    if manifest.get("state",{}).get("completed_duration") is not True:
        fail("manifest does not record completed_duration=true")

    manifest_files=manifest.get("files",{})
    for name in ("paired_books.jsonl","trade_windows.jsonl","state.json"):
        p=root/name
        meta=manifest_files.get(name)
        if not isinstance(meta,dict):
            fail(f"manifest entry missing: {name}")
        actual=sha256_file(p)
        if actual!=meta.get("sha256"):
            fail(f"SHA-256 mismatch: {name}")
        if int(meta.get("bytes",-1))!=p.stat().st_size:
            fail(f"byte-size mismatch: {name}")

    failures=root/"failures.jsonl"
    if failures.exists():
        meta=manifest_files.get("failures.jsonl")
        if not isinstance(meta,dict):
            fail("failures.jsonl exists but manifest entry is missing")
        if sha256_file(failures)!=meta.get("sha256"):
            fail("SHA-256 mismatch: failures.jsonl")
        if int(meta.get("bytes",-1))!=failures.stat().st_size:
            fail("byte-size mismatch: failures.jsonl")

    included=[name for name in REQUIRED if (root/name).exists()]
    included += [name for name in OPTIONAL if (root/name).exists() and name not in included]

    out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(out,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name in included:
            z.write(root/name,arcname=name)

    bundle_sha=sha256_file(out)
    sidecar=out.with_suffix(out.suffix+".sha256")
    sidecar.write_text(f"{bundle_sha}  {out.name}\n",encoding="utf-8")

    print(json.dumps({
        "status":"READY",
        "collector_completed":True,
        "pairs_both_ok":int(state.get("pairs_both_ok",0)),
        "pairs_attempted":int(state.get("pairs_attempted",0)),
        "bundle":str(out),
        "bundle_sha256":bundle_sha,
        "sha256_sidecar":str(sidecar),
        "included_files":included
    },indent=2))

if __name__=="__main__":
    main()
