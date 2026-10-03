import json,tempfile,subprocess,sys
from pathlib import Path
BASE=Path(__file__).parent

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
    cp=subprocess.run([sys.executable,str(BASE/"analyze_f0.py"),"--input",str(root),"--output",str(out)],text=True,capture_output=True)
    assert cp.returncode==0,cp.stderr+cp.stdout
    x=json.loads((out/"f0_results.json").read_text())
    assert x["usable_pairs"]==120
    assert x["minimum_gate_pass"] is False
    s=x["notionals"]["50"]
    assert s["paired_delta_bps_usdc_minus_eur"]["median"]<0
    assert s["EUR"]["insufficient_depth_n"]==0
    assert s["USDC"]["insufficient_depth_n"]==0
    assert (out/"f0_report.md").exists()
    print("F0 synthetic execution-topology test PASS")
