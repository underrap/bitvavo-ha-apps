#!/usr/bin/with-contenv bashio
set -e

OUTPUT="/homeassistant/bitvavo_research/bitvavo_microstructure_week1"

mkdir -p "${OUTPUT}"

echo "Starting Bitvavo Microstructure Collector"
echo "Output: ${OUTPUT}"

exec python3 -u /collect_bitvavo_microstructure.py \
  --output "${OUTPUT}"
