# Bitvavo M1A — Same-Venue Microstructure Information Test

Research-only one-shot Home Assistant app. It never authenticates to Bitvavo and never places orders.

## Purpose
Falsify or support the hypothesis that causally received Bitvavo microstructure contains information about future BTC-EUR price movement before building a strategy.

Primary market: BTC-EUR. BTC-USDC is exploratory only.

## Frozen design
Before analysis, `freeze.py` records a UTC cutoff and copies only records received before that cutoff into a new immutable run directory. SHA-256 hashes are stored in `freeze_manifest.json`. M0 continues collecting after the cutoff; post-cutoff events are untouched future validation data.

M1A uses:
- local monotonic receive time as the causal clock;
- 500 ms decision grid;
- F1 L1 normalized size imbalance;
- F2 first-5-level normalized depth imbalance;
- F3 previous-1000-ms taker buy/sell volume imbalance;
- horizons 0.5s, 1s, 2s, 5s;
- future mid return, current ask→future bid pre-fee markout, and downward sell→future-buy response;
- fixed 10/30/70/90% feature quantiles;
- 60-second time-block bootstrap, 1000 deterministic replicates;
- first/second-half, active/quiet and top-1%-return-trim robustness checks.

No ML, threshold search, indicator search, fee optimization or strategy construction.

## Required M0 version
M0 **1.0.5 or later** is required. Earlier M0 versions did not persist the full reconstructed order-book checkpoint needed to reproduce absolute L1/L5 sizes.

Historical pre-checkpoint raw book deltas remain preserved but are intentionally not used for F1/F2.

## Validity rules
A persisted checkpoint opens a valid book interval. Connect, disconnect, duplicate/stale/forward nonce anomaly, legacy nonce gap, resync failure or exception closes validity until a later checkpoint. Forecast windows crossing invalid grid points are excluded.

The analyzer refuses a frozen dataset whose monotonic receive clock regresses. That protects against silently combining data across a host reboot without an explicit monotonic epoch.

## Output
Each manual run creates:
`/config/bitvavo_research/m1a/runs/<UTC_RUN_ID>/`

with:
- `frozen/` immutable JSONL copies + freeze manifest/hashes;
- `results/results.json` complete machine-readable analysis;
- `results/report.md` compact human report.

## Classification
The analyzer operationalizes the Supervisor's qualitative A/B/C criteria before seeing real M1A results.

An information effect qualifies only when:
1. top-decile minus bottom-decile future-mid response is positive;
2. the 95% 60s block-bootstrap interval is above zero;
3. at least 3 of 4 adjacent conditional-bin means are nondecreasing;
4. the contrast stays positive in first half, second half, and after removing the 1% largest absolute future returns.

C additionally requires positive top-decile ask→future-bid mean markout with its 95% block-bootstrap interval above zero.

This is intentionally conservative and is not a profitability claim. Fees/friction are not included.

## Run behavior
The Home Assistant app is `startup: once` and `boot: manual_only`. Starting it manually creates exactly one frozen run and exits. Do not enable watchdog or start-on-boot.

## Audit limitations
- Standard Bitvavo book-event `timestamp` is not used as the decision clock.
- Quantile ties can expand a group beyond nominal 10/20/40/20/10%; actual N is always reported.
- BTC-USDC must not drive M1A pass/fail.
- A result from a short capture can be statistically weak despite many overlapping 500ms grid points; bootstrap block count and robustness splits matter more than raw N.
