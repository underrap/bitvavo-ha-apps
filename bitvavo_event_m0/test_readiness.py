import json, subprocess, sys, tempfile
from pathlib import Path
BASE=Path(__file__).parent
BOOT="boot-test"
VER="1.0.6"

def write(root,name,rows):
    (root/name).write_text("".join(json.dumps(x)+"\n" for x in rows),encoding="utf-8")

with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    # 3h valid BTC-EUR interval; enough margin for readiness.
    sessions=[
        {"kind":"collector_start","utc_ns":1,"mono_ns":1,"boot_id":BOOT,"session":0,"collector_version":VER},
        {"kind":"connect","utc_ns":2,"mono_ns":2,"boot_id":BOOT,"session":1,"collector_version":VER},
        {"kind":"book_valid","market":"BTC-EUR","utc_ns":3,"mono_ns":3_000_000_000,"boot_id":BOOT,"session":1,"collector_version":VER},
        {"kind":"book_valid","market":"BTC-USDC","utc_ns":4,"mono_ns":4_000_000_000,"boot_id":BOOT,"session":1,"collector_version":VER},
    ]
    raw=[
        {"recv_utc_ns":10_803_000_000_000,"recv_mono_ns":10_803_000_000_000,
         "boot_id":BOOT,"session":1,"collector_version":VER,
         "raw":{"event":"book","market":"BTC-EUR","nonce":1}}
    ]
    cps=[{"kind":"book_checkpoint","market":"BTC-EUR","utc_ns":3,"mono_ns":3_000_000_000,
          "covered_through_recv_mono_ns":3_000_000_000,"snapshot_recv_mono_ns":3_000_000_000,
          "boot_id":BOOT,"session":1,"collector_version":VER,"nonce":1,
          "bids":[["99","1"]],"asks":[["101","1"]]}]
    write(root,"sessions.jsonl",sessions)
    write(root,"raw_events.jsonl",raw)
    write(root,"book_checkpoints.jsonl",cps)
    cp=subprocess.run([sys.executable,str(BASE/"readiness.py"),"--input",str(root)],text=True,capture_output=True)
    assert cp.returncode==0,cp.stderr+cp.stdout
    x=json.loads(cp.stdout)
    assert x["outcome_blind"] is True
    assert x["ready_for_freeze_estimate"] is True,x
    assert x["observed"]["total_valid_seconds"]>7200
    assert x["observed"]["estimated_holdout_valid_seconds"]>2400

with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    sessions=[
        {"kind":"collector_start","utc_ns":1,"mono_ns":1,"boot_id":BOOT,"session":0,"collector_version":VER},
        {"kind":"connect","utc_ns":2,"mono_ns":2,"boot_id":BOOT,"session":1,"collector_version":VER},
        {"kind":"book_valid","market":"BTC-EUR","utc_ns":3,"mono_ns":3_000_000_000,"boot_id":BOOT,"session":1,"collector_version":VER},
        {"kind":"ws_error","utc_ns":603,"mono_ns":603_000_000_000,"boot_id":BOOT,"session":1,"collector_version":VER},
    ]
    raw=[
        {"recv_utc_ns":603_000_000_000,"recv_mono_ns":603_000_000_000,
         "boot_id":BOOT,"session":1,"collector_version":VER,
         "raw":{"event":"book","market":"BTC-EUR","nonce":1}}
    ]
    cps=[{"kind":"book_checkpoint","market":"BTC-EUR","utc_ns":3,"mono_ns":3_000_000_000,
          "covered_through_recv_mono_ns":3_000_000_000,"snapshot_recv_mono_ns":3_000_000_000,
          "boot_id":BOOT,"session":1,"collector_version":VER,"nonce":1,
          "bids":[["99","1"]],"asks":[["101","1"]]}]
    write(root,"sessions.jsonl",sessions)
    write(root,"raw_events.jsonl",raw)
    write(root,"book_checkpoints.jsonl",cps)
    cp=subprocess.run([sys.executable,str(BASE/"readiness.py"),"--input",str(root)],text=True,capture_output=True)
    assert cp.returncode==0
    x=json.loads(cp.stdout)
    assert x["ready_for_freeze_estimate"] is False
    assert x["observed"]["valid_intervals"]==1
    assert x["observed"]["session_event_counts"]["ws_error"]==1

print("M0 readiness gate tests PASS")
