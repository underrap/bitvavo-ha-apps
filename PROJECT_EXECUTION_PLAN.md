# Bitvavo Trading Bot — execution plan to PAPER and small LIVE

Date locked: 2026-10-12

## Objective

Move from research infrastructure to the shortest defensible path to a Smart spot strategy that can be PAPER traded and, only after deterministic execution validation, tested with small LIVE capital.

This plan deliberately prevents research sprawl. F0 and M1A are the only active measurement tracks.

## Current decisions

- Slow Long/Flat Trend: **REJECTED**.
- F0 execution topology: collection complete; existing frozen dataset must be analyzed once.
- M1A FREEZE_001: **INCONCLUSIVE — measurement instrument integrity failure**, not a hypothesis FAIL.
- Repaired M0 collector: **v1.0.6**, main commit lineage includes merge `9148df0af2b1be26cf3e78cb775d80c439a2c179`.
- Next M1A executor: **v1.2.2 / M1A_FREEZE_002**, main merge `fbdb1d6704de34d5bd86e9b015c72908faaa86e8`.
- No new hypothesis class or new collector before F0 and repaired M1A are decided.

## Workstream A — F0: execution-market decision

Input: existing completed F0 week1 dataset.

Run the already merged F0 analyzer exactly once.

Output decision:
- BTC/EUR remains preferred execution market; or
- BTC/USDC is materially cheaper for relevant identical BTC exposure after measured spread/depth/slippage and current fees.

F0 is then CLOSED. It does not create another research round.

## Workstream B — repaired M0 -> M1A

1. Deploy M0 collector v1.0.6 to the Raspberry Pi.
2. Start one fresh prospective dataset in its versioned output directory.
3. Do not append to or modify M0 v1.0.5 / M1A_FREEZE_001.
4. Collect only until there is enough healthy, contiguous causal coverage with margin for the frozen M1A minimum-data gate. Do not impose another arbitrary seven-day wait.
5. Stop collector, freeze as `M1A_FREEZE_002`, generate provenance, run pre-run gate.
6. Execute M1A exactly once.

Decision:
- PASS -> immediately build M1B economic/execution strategy translation.
- FAIL -> close the simple same-venue microstructure feature class.
- INCONCLUSIVE -> only instrumentation/integrity defects may justify another collection; no rescue tuning.

M1A features, horizons, split, bootstrap and PASS/FAIL rules remain unchanged.

## Workstream C — production PAPER/LIVE runtime

This runs in parallel with M0 collection and does not wait for M1A results.

Production runtime must prove, in the actual bot source:
- durable clientOrderId before network placement;
- authoritative order/fill lifecycle;
- append-only idempotent fills;
- accounting from settled actual fills and actual fees;
- idempotent SQLite migration preserving historic P/L;
- restart and reconnect reconciliation before new placements;
- PAPER/LIVE write-path isolation;
- PAUSED and SAFE_HALT semantics;
- current market rules and authenticated fee schedule;
- private order/fill stream plus continuous reconciliation fallback;
- LIVE refusal for withdrawal-enabled API keys;
- explicit max-order notional and total exposure cap;
- Cancel on disconnect when resting orders are possible.

No strategy logic should be changed during this pass.

## Workstream D — money path

If M1A PASS:
1. M1B converts the information edge into explicit causal entry/exit/order rules.
2. Backtest with actual fees, spread/slippage assumptions and capital lock.
3. Freeze candidate.
4. Forward PAPER.
5. If execution/accounting behavior matches the frozen expectations, start a small LIVE pilot.
6. Scale only after measured LIVE fills/reconciliation/P&L agree with the model.

Initial LIVE is a validation stage, not full deployment. Use only a limited portion of the EUR 500 test capital until the runtime and economics are proven in the real venue.

If M1A FAIL:
- no rescue parameter sweep of the same information layer;
- at most one materially different causal hypothesis class, and only if the collected evidence motivates it.

## Definition of progress

Progress is not another report or collector. Progress means one of:
- an execution-market decision;
- a PASS/FAIL M1A decision;
- a PAPER-ready strategy candidate;
- a passed production-runtime safety gate;
- a small LIVE validation with reconciled fills and accounting.

## Work-mode boundary

GitHub/repository engineering should be done directly through the repository connector when possible.

Use ChatGPT Work only when the task genuinely requires one substantial pass over the user's local production workspace or browser/computer environment. When Work is needed, batch the full task into one handoff with explicit acceptance criteria; do not use Work for iterative back-and-forth implementation.
