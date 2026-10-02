#!/usr/bin/with-contenv bashio
set -euo pipefail

echo "M1A-PREREG-v1.3 executor branch"
echo "STATUS: FROZEN-SPEC / EXECUTION BLOCKED"
echo "Refusing to freeze or analyze market data until:"
echo "  1) bitvavo_m1a v1.2.0 exactly implements protocol_v1_3.json"
echo "  2) synthetic/fixture conformance tests pass"
echo "  3) execution commit SHA is pinned"
echo "  4) M1A_FREEZE_001 provenance is complete"
exit 64
