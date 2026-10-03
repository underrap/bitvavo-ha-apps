# Bitvavo M1A — Same-Venue Microstructure Information Test

Research-only executor for **M1A-PREREG-v1.3**. It never authenticates to Bitvavo and never places orders.

## Status

`FROZEN-SPEC / EXECUTION BLOCKED`

The executor implementation is complete on the dedicated branch, but real M1A market data must not be analyzed until the exact execution commit and `M1A_FREEZE_001` provenance are pinned and the pre-run gate passes.

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
- TFI state is reset at every persisted checkpoint / hard segment boundary
- any target crossing an invalid grid point or segment boundary is excluded
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

## Pre-run provenance gate

The Home Assistant app does **not** create a new freeze at startup. It analyzes only the already prepared:

`/homeassistant/bitvavo_research/m1a/M1A_FREEZE_001/frozen`

and requires:

`/homeassistant/bitvavo_research/m1a/M1A_FREEZE_001/execution_provenance.json`

The runner hard-stops unless:
- the mandatory Home Assistant app option `execution_commit_sha` is set to the pinned 40-character execution SHA;
- that configured SHA equals `execution_commit_sha` in the provenance record;
- protocol = `M1A-PREREG-v1.3`;
- executor version = `1.2.0`;
- freeze id = `M1A_FREEZE_001`;
- M0 version = `1.0.5`;
- protocol conformance status = `PASS`;
- freeze manifest SHA-256 matches;
- every frozen raw file SHA-256 matches the manifest and provenance record;
- research cutoff and first/last event UTC match the frozen manifest;
- the results directory is still empty.

The app configuration schema validates `execution_commit_sha` as exactly 40 lowercase hexadecimal characters. The app must be built/deployed from that pinned commit; the pre-run gate then requires the configured SHA and provenance record to agree.

No M1A result may be inspected before this gate is complete.

## Tests

CI uses synthetic/fixture data only. It verifies:
- frozen protocol constants;
- freeze cutoff/hash behavior;
- pre-run provenance rejection/pass behavior;
- TFI reset at hard segment boundaries;
- rejection of targets crossing invalid/intermediate grid states;
- end-to-end INCONCLUSIVE behavior on deliberately undersized synthetic data.

The tests must never read the real M0 research dataset.
