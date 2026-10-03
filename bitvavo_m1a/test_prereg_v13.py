import importlib.util
import json
from pathlib import Path

BASE = Path(__file__).parent
SPEC = json.loads((BASE / "protocol_v1_3.json").read_text())

spec = importlib.util.spec_from_file_location("m1a_analyze", BASE / "analyze.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

assert getattr(m, "VERSION", None) == "1.2.0"
assert getattr(m, "GRID_NS", None) == 500_000_000
assert getattr(m, "LOOKBACK_NS", None) == 1_000_000_000
assert tuple(getattr(m, "HORIZONS_NS", ())) == (500_000_000, 1_000_000_000, 2_000_000_000, 5_000_000_000)
assert getattr(m, "BLOCK_NS", None) == 60_000_000_000
assert getattr(m, "BOOTSTRAPS", None) == 10_000
assert getattr(m, "SEED", None) == 20261002

print("Static prereg constants PASS")
