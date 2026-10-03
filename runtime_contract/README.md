# Runtime mode, migration and LIVE-safety acceptance contract

Status: **reference/test contract — no runtime dependency**

This is the remaining strategy-independent safety boundary for the local production bot.
It complements `execution_contract/` and `accounting_contract/`.

## Startup contract

The production process may be configured as PAPER or LIVE, but a LIVE process starts in
**RECOVERING**, not by immediately resuming placement.

Before LIVE writes are allowed, all of these must be true:

- database schema/migrations are current;
- persisted local state has been loaded;
- balances are reconciled with exchange `available + inOrder`;
- open/local orders are reconciled against Bitvavo authoritative state;
- there are no unknown exchange orders owned by this bot;
- no fill with economically relevant missing settlement/fee data remains unresolved;
- current market metadata is loaded;
- current authenticated fee schedule is loaded;
- market status is `trading`;
- API key has read + trade and no withdrawal permission;
- explicit max order notional is configured;
- explicit total exposure cap is configured;
- kill-switch behavior has passed its deterministic test;
- authenticated order/fill stream tracking is operational;
- periodic/continuous reconciliation of live order/balance state is operational as a fallback to the stream;
- if the strategy can leave limit/trigger orders resting on Bitvavo, Cancel on disconnect is configured and its heartbeat path is tested.

Unknown/missing state means **fail closed**.

### Cancel on disconnect

Bitvavo supports `cancelOrdersAfter` / `codGroupId` for resting orders. The exchange
cancels the grouped open orders when the bot stops refreshing the countdown. The documented
minimum expiry is 10 seconds; Bitvavo's example recommends refreshing a 30-second timer about
every 15 seconds.

This is a valuable network-failure safety layer, but it does **not** apply to market orders and
does not replace restart reconciliation. A production strategy that never leaves resting orders
may mark this gate not-applicable rather than pretending COD protects market orders.

Source: https://docs.bitvavo.com/docs/cancel-on-disconnect/

### Continuous reconciliation

A healthy private WebSocket stream is necessary but not sufficient. Mature public trading engines
also periodically reconcile in-flight/open orders and account/position state against the venue.
This catches missed events and stale local state even when the process itself did not restart.

The production bot should therefore use:
- Bitvavo authenticated order/fill tracking as the fast path;
- periodic authoritative order/balance reconciliation as the safety path;
- placement blocking when either path reports an unresolved discrepancy.

Public framework benchmark:
- NautilusTrader startup + continuous reconciliation;
- Hummingbot ClientOrderTracker/UserStreamTracker plus recovery QA;
- Freqtrade persistent trade/order state with recurring exchange order updates.

See `PUBLIC_FRAMEWORK_BENCHMARK.md`.

## Pause semantics

`PAUSED` means **no new exposure**.

It does not mean “stop looking after everything already open.” While paused the runtime may:

- cancel pending entry orders;
- maintain/cancel exit orders;
- perform an explicitly risk-reducing exit.

It may not place a new entry or otherwise increase exposure.

This prevents the common failure mode where a “pause” button leaves existing risk unmanaged.

## Safe-halt / kill-switch semantics

`SAFE_HALT`:

- blocks all new/increased exposure immediately;
- permits cancellation of bot-owned open orders;
- permits an explicitly risk-reducing exit;
- does **not** silently market-sell the whole position.

Automatic emergency liquidation would itself be an execution strategy and can create slippage.
It therefore requires a separate explicit design decision rather than being hidden inside a kill switch.

## Database migration acceptance criteria

The exact current SQLite schema lives in the local bot and is not present in this repository,
so this contract does not invent DDL. A production migration is acceptable only if it proves:

- migration version is persisted and rerunning the migration is idempotent;
- existing historical trades/lots/accounting rows are preserved;
- `clientOrderId`, market-scoped `orderId`, order status, fill IDs, fill amounts, actual fee,
  fee currency and settlement state can be persisted without lossy conversion;
- the logical uniqueness rules required by execution recovery are enforced;
- no schema change silently changes old P/L;
- migration failure prevents LIVE startup;
- backup/rollback procedure is tested before applying a destructive migration;
- restart after migration can reconcile local state to Bitvavo without placing an order first.

## PAPER/LIVE isolation

PAPER and LIVE may share pure strategy/decision code, but must not share write paths:

- PAPER cannot call authenticated create/update/cancel order endpoints;
- LIVE order placement requires the LIVE gate;
- a mode switch cannot retroactively reinterpret paper fills as exchange fills;
- database rows must carry enough provenance to distinguish PAPER, LIVE and replay/backtest events.

## Integration target

When the local bot source is available, the first production hardening pass should target:

- `execution.py`: intent IDs, order/fill lifecycle, retry policy, market/fee rules;
- `bot.py`: startup recovery, mode gate, key permission check, pause/kill-switch enforcement;
- SQLite migrations: durable intent/order/fill/accounting fields and mode provenance;
- dashboard: surface blocked/recovering/paused state without mixing it with strategy signals.

No Smart strategy should gain LIVE permission merely because this contract exists.
