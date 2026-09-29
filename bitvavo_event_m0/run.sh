#!/usr/bin/with-contenv bashio
set -e
OUTPUT="/homeassistant/bitvavo_research/event_m0"
mkdir -p "${OUTPUT}"
cp /quality_report.py "${OUTPUT}/quality_report.py"
echo "Starting Bitvavo Event-Level Research Collector M0"
echo "Output: ${OUTPUT}"
echo "Research only: public market data; NO API key; NO orders."
exec python3 -u /collect_event_m0.py --output "${OUTPUT}"
