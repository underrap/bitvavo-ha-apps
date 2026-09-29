#!/usr/bin/with-contenv bashio
set -e
OUTPUT="/homeassistant/bitvavo_research/event_m0"
mkdir -p "${OUTPUT}"
echo "Starting Bitvavo Event-Level Research Collector M0"
echo "Output: ${OUTPUT}"
exec python3 -u /collect_event_m0.py --output "${OUTPUT}"
