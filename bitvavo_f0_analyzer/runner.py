from pathlib import Path
import subprocess, sys

INPUT=Path("/homeassistant/bitvavo_research/bitvavo_microstructure_week1")
OUTPUT=Path("/homeassistant/bitvavo_research/f0_analysis_001")

if not INPUT.is_dir():
    raise SystemExit(f"F0 STOP: completed collector directory missing: {INPUT}")
if OUTPUT.exists() and any(OUTPUT.iterdir()):
    raise SystemExit(f"F0 STOP: output directory is not empty; refusing a second run: {OUTPUT}")

OUTPUT.mkdir(parents=True,exist_ok=True)
print("Starting one-shot F0 execution-topology analysis")
print("Input: ",INPUT)
print("Output:",OUTPUT)
print("Research only; public data; NO API key; NO orders.")

cp=subprocess.run(
    [sys.executable,"/analyze_f0.py","--input",str(INPUT),"--output",str(OUTPUT)],
    check=False
)
raise SystemExit(cp.returncode)
