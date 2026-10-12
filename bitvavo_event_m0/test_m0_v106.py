import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path

# Keep CI dependency-free: the tests exercise collector state transitions and
# checkpoint watermark logic, not real network I/O.
sys.modules.setdefault("requests", types.SimpleNamespace(get=None))
sys.modules.setdefault("websocket", types.SimpleNamespace(WebSocketApp=None))

BASE=Path(__file__).parent
spec=importlib.util.spec_from_file_location("m0", BASE/"collect_event_m0.py")
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

assert m.VERSION=="1.0.6"

# Causal checkpoint watermark must cover the REST snapshot and every raw book
# event actually incorporated into the checkpoint, but not a concurrent event
# that was recorded while blocked on the book lock and therefore is not covered.
buffered=[
    {"recv_mono_ns":90,"raw":{"nonce":10}},
    {"recv_mono_ns":95,"raw":{"nonce":11}},
]
assert m.checkpoint_watermark(100,buffered,11)==100
buffered.append({"recv_mono_ns":120,"raw":{"nonce":12}})
assert m.checkpoint_watermark(100,buffered,12)==120
assert m.checkpoint_watermark(100,buffered,11)==100

class FakeWS:
    def __init__(self):
        self.sent=[]
        self.closed=0
    def send(self,x):
        self.sent.append(json.loads(x))
    def close(self):
        self.closed+=1

with tempfile.TemporaryDirectory() as d:
    c=m.Collector(Path(d))
    ws=FakeWS()
    c.ws=ws
    c.on_open(ws)
    assert c.session==1
    assert ws.sent and ws.sent[-1]["action"]=="subscribe"

    # Put a market in a valid state, then deliver a duplicate nonce. Bitvavo's
    # documented recovery rule requires restarting from subscription step 1.
    b=c.books["BTC-EUR"]
    with c.book_locks["BTC-EUR"]:
        b.update(valid=True,nonce=100,bids={"99":"1"},asks={"101":"1"},buffer=[],syncing=False)

    c.on_message(ws,json.dumps({
        "event":"book","market":"BTC-EUR","nonce":100,
        "bids":[["99","1.1"]],"asks":[]
    }))
    assert ws.closed==1
    assert c.reconnect_requested is True
    assert all(not x["valid"] for x in c.books.values())

    rows=[json.loads(x) for x in (Path(d)/"sessions.jsonl").read_text().splitlines()]
    kinds=[x["kind"] for x in rows]
    assert "duplicate_nonce" in kinds
    assert "full_resubscribe_required" in kinds
    assert all("boot_id" in x for x in rows)
    assert all(x["collector_version"]=="1.0.6" for x in rows)

print("M0 v1.0.6 resilience tests PASS")
