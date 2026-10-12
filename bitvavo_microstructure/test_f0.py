import hashlib,json,tempfile,subprocess,sys
from pathlib import Path
BASE=Path(__file__).parent

def sha(p):
    h=hashlib.sha256();h.update(p.read_bytes());return h.hexdigest()

def book(m,bid,ask,depth=100):
    bids=[[str(bid-i),"10"] for i in range(depth)]
    asks=[[str(ask+i),"10"] for i in range(depth)]
    return {"ok":True,"local_send_ms":1000,"local_recv_ms":1010,"latency_ms":10,
            "response":{"market":m,"nonce":1,"timestamp":1,"bids":bids,"asks":asks}}

with tempfile.TemporaryDirectory() as d:
    root=Path(d)/"in";out=Path(d)/"out";root.mkdir()
    rows=[]
    for i in range(120):
        t=1_800_000_000_000+i*60_000
        rows.append({"schema":1,"pair_id":str(i),"collector_start_ms":t,"collector_end_ms":t+25,
                     "pair_elapsed_ms":25,"depth":100,"both_ok":True,
                     "books":{"BTC-EUR":book("BTC-EUR",49999,50001),
                              "BTC-USDC":book("BTC-USDC",49999.5,50000.5)}})
    (root/"paired_books.jsonl").write_text("".join(json.dumps(x)+"\n" for x in rows))
    (root/"trade_windows.jsonl").write_text("")
    (root/"failures.jsonl").write_text("")
    state={"completed_duration":True,"first_pair_ms":1_800_000_000_000,
           "stopped_at":"2026-10-09T18:45:39Z","pairs_both_ok":120,"pairs_attempted":120}
    (root/"state.json").write_text(json.dumps(state,separators=(",",":")))
    files={}
    for name in ("paired_books.jsonl","trade_windows.jsonl","failures.jsonl","state.json"):
        p=root/name
        files[name]={"bytes":p.stat().st_size,"sha256":sha(p)}
    manifest={"version":1,"public_only":True,"book_depth":100,"state":state,"files":files}
    (root/"manifest.json").write_text(json.dumps(manifest,separators=(",",":")))

    cp=subprocess.run([sys.executable,str(BASE/"analyze_f0.py"),"--input",str(root),"--output",str(out)],
                      text=True,capture_output=True)
    assert cp.returncode==0,cp.stderr+cp.stdout
    x=json.loads((out/"f0_results.json").read_text())
    assert x["version"]=="1.1.0"
    assert x["input"]["input_gate"]=="PASS"
    assert x["usable_pairs"]==120
    assert x["minimum_gate_pass"] is False
    s=x["notionals"]["50"]
    assert s["paired_delta_bps_usdc_minus_eur"]["median"]<0
    assert s["EUR"]["insufficient_depth_n"]==0
    assert s["USDC"]["insufficient_depth_n"]==0
    assert (out/"f0_report.md").exists()

    # Tampering after manifest creation must fail before analysis.
    with (root/"paired_books.jsonl").open("a") as fh:
        fh.write("{}\n")
    cp=subprocess.run([sys.executable,str(BASE/"analyze_f0.py"),"--input",str(root),"--output",str(Path(d)/"bad")],
                      text=True,capture_output=True)
    assert cp.returncode!=0
    assert "SHA-256 mismatch" in (cp.stderr+cp.stdout)
    print("F0 synthetic execution-topology test PASS")
