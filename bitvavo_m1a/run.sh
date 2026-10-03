#!/usr/bin/with-contenv bashio
set -euo pipefail

ROOT="/homeassistant/bitvavo_research/m1a/M1A_FREEZE_001"
FROZEN="${ROOT}/frozen"
PROVENANCE="${ROOT}/execution_provenance.json"
RESULTS="${ROOT}/results"

EXECUTION_COMMIT_SHA="$(bashio::config 'execution_commit_sha')"
if [ -z "${EXECUTION_COMMIT_SHA}" ]; then
  echo "M1A PRE-RUN GATE: FAIL — execution_commit_sha is not configured"
  exit 64
fi

if [ -d "${RESULTS}" ] && [ -n "$(ls -A "${RESULTS}" 2>/dev/null)" ]; then
  echo "M1A PRE-RUN GATE: FAIL — results directory is not empty: ${RESULTS}"
  exit 64
fi

mkdir -p "${RESULTS}"

echo "M1A-PREREG-v1.3 pre-run provenance gate..."
python3 -u /pre_run_gate.py   --freeze "${FROZEN}"   --provenance "${PROVENANCE}"   --execution-commit "${EXECUTION_COMMIT_SHA}"

echo "Gate PASS. Running exactly one frozen M1A analysis..."
python3 -u /analyze.py --input "${FROZEN}" --output "${RESULTS}"

echo "M1A complete."
echo "Report: ${RESULTS}/report.md"
echo "Machine-readable: ${RESULTS}/results.json"
