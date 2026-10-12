import importlib.util,json,tempfile
from pathlib import Path
BASE=Path(__file__).parent
spec=importlib.util.spec_from_file_location("m1a",BASE/"analyze.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

# Target must reject any invalid intermediate grid point.
rows=[]
for i in range(11):
 rows.append({"t":i*m.GRID_NS,"segment":0,"valid":True,"mid":100+i,"f1":0.1,"f2":0.1,"f3":0.0})
assert m.row_target(rows,0,5_000_000_000) is not None
rows[5]["valid"]=False
assert m.row_target(rows,0,5_000_000_000) is None
rows[5]["valid"]=True;rows[5]["segment"]=1
assert m.row_target(rows,0,5_000_000_000) is None

# M0 v1.0.6 checkpoint watermark: events at/before the causal coverage watermark
# are already incorporated, while later events must be replayed.
with tempfile.TemporaryDirectory() as d:
 root=Path(d)
 boot="boot-a";t0=10_000_000_000;utc0=100_000_000_000
 sessions=[
  {"kind":"collector_start","utc_ns":utc0-1,"mono_ns":t0-1,"boot_id":boot,"session":0,"collector_version":"1.0.6"},
  {"kind":"connect","utc_ns":utc0,"mono_ns":t0,"boot_id":boot,"session":1,"collector_version":"1.0.6"},
 ]
 cps=[
  {"market":"BTC-EUR","boot_id":boot,"collector_version":"1.0.6","session":1,
   "mono_ns":t0,"covered_through_recv_mono_ns":t0,"snapshot_recv_mono_ns":t0,
   "utc_ns":utc0,"nonce":10,
   "bids":[["99","1"],["98","1"],["97","1"],["96","1"],["95","1"]],
   "asks":[["101","1"],["102","1"],["103","1"],["104","1"],["105","1"]]}
 ]
 raw=[
  {"boot_id":boot,"collector_version":"1.0.6","session":1,
   "recv_mono_ns":t0,"recv_utc_ns":utc0,
   "raw":{"market":"BTC-EUR","event":"book","nonce":10,"bids":[["99","1"]],"asks":[]}},
  {"boot_id":boot,"collector_version":"1.0.6","session":1,
   "recv_mono_ns":t0+250_000_000,"recv_utc_ns":utc0+250_000_000,
   "raw":{"market":"BTC-EUR","event":"book","nonce":11,"bids":[["99","2"]],"asks":[]}},
  {"boot_id":boot,"collector_version":"1.0.6","session":1,
   "recv_mono_ns":t0+750_000_000,"recv_utc_ns":utc0+750_000_000,
   "raw":{"market":"BTC-EUR","event":"book","nonce":12,"bids":[["100","1"]],"asks":[["101","0"],["102","1"]]}},
  {"boot_id":boot,"collector_version":"1.0.6","session":1,
   "recv_mono_ns":t0+1_250_000_000,"recv_utc_ns":utc0+1_250_000_000,
   "raw":{"market":"BTC-EUR","event":"book","nonce":13,"bids":[["100","2"]],"asks":[]}},
 ]
 (root/"sessions.jsonl").write_text("".join(json.dumps(x)+"\n" for x in sessions))
 (root/"book_checkpoints.jsonl").write_text("".join(json.dumps(x)+"\n" for x in cps))
 (root/"raw_events.jsonl").write_text("".join(json.dumps(x)+"\n" for x in raw))
 grid,audit=m.build_grid(root,"BTC-EUR")
 assert audit["monotonic_regressions"]==0,audit
 assert audit.get("nonce_anomalies_replay",0)==0,audit
 assert grid,grid
 # The covered nonce=10 raw event must not be replayed as a duplicate.
 assert all(r["segment"]==0 for r in grid)

# Explicit boot_id restart is a hard causal boundary and may reset monotonic time.
with tempfile.TemporaryDirectory() as d:
 root=Path(d)
 b1="boot-1";b2="boot-2"
 sessions=[
  {"kind":"collector_start","utc_ns":100_000_000_000,"mono_ns":9_000_000_000,"boot_id":b1,"session":0,"collector_version":"1.0.6"},
  {"kind":"connect","utc_ns":101_000_000_000,"mono_ns":10_000_000_000,"boot_id":b1,"session":1,"collector_version":"1.0.6"},
  {"kind":"collector_start","utc_ns":200_000_000_000,"mono_ns":500_000_000,"boot_id":b2,"session":0,"collector_version":"1.0.6"},
  {"kind":"connect","utc_ns":201_000_000_000,"mono_ns":1_000_000_000,"boot_id":b2,"session":1,"collector_version":"1.0.6"},
 ]
 cps=[
  {"market":"BTC-EUR","boot_id":b1,"collector_version":"1.0.6","session":1,
   "mono_ns":10_000_000_000,"covered_through_recv_mono_ns":10_000_000_000,"snapshot_recv_mono_ns":10_000_000_000,
   "utc_ns":101_000_000_000,"nonce":10,
   "bids":[["99","1"],["98","1"],["97","1"],["96","1"],["95","1"]],
   "asks":[["101","1"],["102","1"],["103","1"],["104","1"],["105","1"]]},
  {"market":"BTC-EUR","boot_id":b2,"collector_version":"1.0.6","session":1,
   "mono_ns":1_000_000_000,"covered_through_recv_mono_ns":1_000_000_000,"snapshot_recv_mono_ns":1_000_000_000,
   "utc_ns":201_000_000_000,"nonce":20,
   "bids":[["99","1"],["98","1"],["97","1"],["96","1"],["95","1"]],
   "asks":[["101","1"],["102","1"],["103","1"],["104","1"],["105","1"]]},
 ]
 raw=[
  {"boot_id":b1,"collector_version":"1.0.6","session":1,"recv_mono_ns":10_250_000_000,"recv_utc_ns":101_250_000_000,
   "raw":{"market":"BTC-EUR","event":"book","nonce":11,"bids":[["99","1.1"]],"asks":[]}},
  {"boot_id":b1,"collector_version":"1.0.6","session":1,"recv_mono_ns":10_750_000_000,"recv_utc_ns":101_750_000_000,
   "raw":{"market":"BTC-EUR","event":"book","nonce":12,"bids":[["99","1.2"]],"asks":[]}},
  {"boot_id":b2,"collector_version":"1.0.6","session":1,"recv_mono_ns":1_250_000_000,"recv_utc_ns":201_250_000_000,
   "raw":{"market":"BTC-EUR","event":"book","nonce":21,"bids":[["99","1.1"]],"asks":[]}},
  {"boot_id":b2,"collector_version":"1.0.6","session":1,"recv_mono_ns":1_750_000_000,"recv_utc_ns":201_750_000_000,
   "raw":{"market":"BTC-EUR","event":"book","nonce":22,"bids":[["99","1.2"]],"asks":[]}},
  {"boot_id":b2,"collector_version":"1.0.6","session":1,"recv_mono_ns":2_250_000_000,"recv_utc_ns":202_250_000_000,
   "raw":{"market":"BTC-EUR","event":"book","nonce":23,"bids":[["99","1.3"]],"asks":[]}},
 ]
 (root/"sessions.jsonl").write_text("".join(json.dumps(x)+"\n" for x in sessions))
 (root/"book_checkpoints.jsonl").write_text("".join(json.dumps(x)+"\n" for x in cps))
 (root/"raw_events.jsonl").write_text("".join(json.dumps(x)+"\n" for x in raw))
 grid,audit=m.build_grid(root,"BTC-EUR")
 assert audit["explicit_boot_epochs"]==2,audit
 assert audit["monotonic_regressions"]==0,audit
 assert {r["epoch"] for r in grid}=={0,1},grid
 e0=[i for i,r in enumerate(grid) if r["epoch"]==0]
 e1=[i for i,r in enumerate(grid) if r["epoch"]==1]
 assert e0 and e1 and max(e0)<min(e1)
 assert grid[max(e0)]["segment"] != grid[min(e1)]["segment"]
 assert m.row_target(grid,max(e0),m.PRIMARY_H_NS) is None
print("M1A v1.2.2 causal checkpoint/restart regressions PASS")
