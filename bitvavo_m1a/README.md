# Bitvavo M1A — Same-Venue Microstructure Information Test

Research-only executor for **M1A-PREREG-v1.3**. It never authenticates to Bitvavo and never places orders.

## Status

`FROZEN-SPEC / EXECUTION BLOCKED`

The executor implementation lives on the dedicated branch, but real M1A market data must not be analyzed until the execution commit and `M1A_FREEZE_001` provenance are pinned and the pre-run audit passes.

## Frozen research design

Content rules are identical to `M1A-PREREG-v1.2`.

Primary:
- BTC-EUR
- L1 normalized book imbalance
- 1-second future mid-price markout
- Spearman rho on untouched HOLDOUT

Secondary only:
- depth-5 imbalance
- signed 1-second trade-flow imbalance
- 0.5s, 2s and 5s horizons
- BTC-USDC descriptive only

Causal rules:
- local monotonic receive time
- 500ms decision grid
- no interpolation
- reconnect/restart/book invalidation is a hard segment boundary
- M0 1.0.5 persisted reconstructed-book checkpoints are required

Discovery/Holdout:
- primary-eligible BTC-EUR observations
- first 60% DISCOVERY
- final 40% HOLDOUT
- DISCOVERY freezes q20/q80 thresholds
- HOLDOUT is opened once

Confirmatory bootstrap:
- moving-block bootstrap
- 60-second blocks
- 10,000 resamples
- seed 20261002
- percentile 95% CI
- one-sided p = `(1 + count(rho_star <= 0)) / 10001`

PASS requires all frozen conditions:
1. HOLDOUT rho > 0
2. p < 0.05
3. percentile CI lower bound > 0
4. q80-q20 contrast > 0
5. at least 3 of 4 HOLDOUT quarter rhos > 0
6. signed 1%/99% trimmed rho > 0

Minimum-data failure yields `INCONCLUSIVE`, never PASS/FAIL.

## Safety gate

`run.sh` intentionally refuses real execution while provenance is incomplete.

Before RUN, pin:
- exact execution commit SHA
- executor version 1.2.0
- `M1A_FREEZE_001`
- research cutoff
- freeze manifest path + SHA-256
- raw source paths + SHA-256
- first/last event UTC
- M0 1.0.5 provenance/capability
- passing protocol-conformance tests

No M1A result may be inspected before this gate is complete.

## Tests

Tests use synthetic/fixture data only. They must not read the real M0 research dataset.
