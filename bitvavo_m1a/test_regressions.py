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

# TFI must reset at persisted checkpoint / hard segment boundary.
with tempfile.TemporaryDirectory() as d:
 root=Path(d)
 t0=10_000_000_000
 cps=[
  {"market":"BTC-EUR","mono_ns":t0,"utc_ns":1_000_000_000,"nonce":10,
   "bids":[["99","1"],["98","1"],["97","1"],["96","1"],["95","1"]],
   "asks":[["101","1"],["102","1"],["103","1"],["104","1"],["105","1"]]},
  {"market":"BTC-EUR","mono_ns":t0+1_000_000_000,"utc_ns":2_000_000_000,"nonce":20,
   "bids":[["99","1"],["98","1"],["97","1"],["96","1"],["95","1"]],
   "asks":[["101","1"],["102","1"],["103","1"],["104","1"],["105","1"]]}
 ]
 raw=[
  {"recv_mono_ns":t0-400_000_000,"recv_utc_ns":600_000_000,"raw":{"market":"BTC-EUR","event":"trade","side":"buy","amount":"1"}},
  {"recv_mono_ns":t0+400_000_000,"recv_utc_ns":1_400_000_000,"raw":{"market":"BTC-EUR","event":"trade","side":"buy","amount":"1"}},
  {"recv_mono_ns":t0+1_250_000_000,"recv_utc_ns":2_250_000_000,"raw":{"market":"BTC-EUR","event":"book","nonce":21,"bids":[["99","1"]],"asks":[]}},
  {"recv_mono_ns":t0+1_750_000_000,"recv_utc_ns":2_750_000_000,"raw":{"market":"BTC-EUR","event":"book","nonce":22,"bids":[["99","1"]],"asks":[]}},
  {"recv_mono_ns":t0+2_250_000_000,"recv_utc_ns":3_250_000_000,"raw":{"market":"BTC-EUR","event":"book","nonce":23,"bids":[["99","1"]],"asks":[]}}
 ]
 (root/"book_checkpoints.jsonl").write_text("".join(json.dumps(x)+"\n" for x in cps))
 (root/"raw_events.jsonl").write_text("".join(json.dumps(x)+"\n" for x in raw))
 (root/"sessions.jsonl").write_text("")
 grid,audit=m.build_grid(root,"BTC-EUR")
 first=[r for r in grid if r["segment"]==0 and r["valid"]]
 assert first,grid
 assert first[0]["f3"]==0.0,first[0]  # pre-checkpoint trade must not seed TFI
 post=[r for r in grid if r["segment"]==1 and r["valid"]]
 assert post,grid
 assert post[0]["f3"]==0.0,post[0]
 assert audit.get("tradeflow_segment_resets",0)>=1
print("M1A segment/target regression PASS")


# A host/process restart legitimately resets time.monotonic_ns(). It must become
# a hard causal epoch boundary, never a fatal global regression and never a
# stitched target/trade-flow window.
with tempfile.TemporaryDirectory() as d:
 root=Path(d)
 sessions=[
  {"kind":"connect","utc_ns":100_000_000_000,"mono_ns":9_000_000_000,"session":1},
  {"kind":"connect","utc_ns":200_000_000_000,"mono_ns":1_000_000_000,"session":1},
 ]
 cps=[
  {"market":"BTC-EUR","mono_ns":10_000_000_000,"utc_ns":101_000_000_000,"nonce":10,
   "bids":[["99","1"],["98","1"],["97","1"],["96","1"],["95","1"]],
   "asks":[["101","1"],["102","1"],["103","1"],["104","1"],["105","1"]]},
  {"market":"BTC-EUR","mono_ns":2_000_000_000,"utc_ns":201_000_000_000,"nonce":20,
   "bids":[["99","1"],["98","1"],["97","1"],["96","1"],["95","1"]],
   "asks":[["101","1"],["102","1"],["103","1"],["104","1"],["105","1"]]},
 ]
 raw=[
  {"recv_mono_ns":10_250_000_000,"recv_utc_ns":101_250_000_000,
   "raw":{"market":"BTC-EUR","event":"book","nonce":11,"bids":[["99","1.1"]],"asks":[]}},
  {"recv_mono_ns":10_750_000_000,"recv_utc_ns":101_750_000_000,
   "raw":{"market":"BTC-EUR","event":"book","nonce":12,"bids":[["99","1.2"]],"asks":[]}},
  {"recv_mono_ns":2_250_000_000,"recv_utc_ns":201_250_000_000,
   "raw":{"market":"BTC-EUR","event":"book","nonce":21,"bids":[["99","1.1"]],"asks":[]}},
  {"recv_mono_ns":2_750_000_000,"recv_utc_ns":201_750_000_000,
   "raw":{"market":"BTC-EUR","event":"book","nonce":22,"bids":[["99","1.2"]],"asks":[]}},
  {"recv_mono_ns":3_250_000_000,"recv_utc_ns":202_250_000_000,
   "raw":{"market":"BTC-EUR","event":"book","nonce":23,"bids":[["99","1.3"]],"asks":[]}},
 ]
 (root/"sessions.jsonl").write_text("".join(json.dumps(x)+"\n" for x in sessions))
 (root/"book_checkpoints.jsonl").write_text("".join(json.dumps(x)+"\n" for x in cps))
 (root/"raw_events.jsonl").write_text("".join(json.dumps(x)+"\n" for x in raw))
 grid,audit=m.build_grid(root,"BTC-EUR")
 assert audit["restart_epoch_boundaries"]==1,audit
 assert audit["monotonic_global_regressions"]==1,audit
 assert audit["monotonic_regressions"]==0,audit
 assert {r["epoch"] for r in grid}=={0,1},grid
 e0=[i for i,r in enumerate(grid) if r["epoch"]==0]
 e1=[i for i,r in enumerate(grid) if r["epoch"]==1]
 assert e0 and e1
 assert max(e0)<min(e1)
 assert grid[max(e0)]["segment"] != grid[min(e1)]["segment"]
 assert m.row_target(grid,max(e0),m.PRIMARY_H_NS) is None
print("M1A restart-epoch regression PASS")
