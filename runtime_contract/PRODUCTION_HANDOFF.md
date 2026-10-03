# Production runtime integration handoff

Purpose: let the **02 - Codex & Botontwikkeling** workflow apply the portable safety contracts to the actual bot without using the user as a message bus.

## Production source of truth

Local workspace:

`C:\Users\hbang\OneDrive\Documenten\ChatGPT\Bitvavo Trading Bot`

Known production/runtime structure:

- `execution.py` — quotes / intents / fills / execution;
- `bot.py` — Bitvavo API, SQLite and runtime adapter;
- `smart_core.py` — shared Smart state/decision logic;
- `replay_foundation.py` — deterministic replay;
- `dashboard.py` — Flask dashboard;
- shared SQLite/config.

Research collectors/analyzers in `underrap/bitvavo-ha-apps` must remain separate and must not become production runtime dependencies.

## Implementation order

Do not change strategy behavior while performing this hardening pass.

### 1. Inventory and protect the current database

Before writing a migration:

- inspect current SQLite schema, indexes and all code paths that write order/trade/lot/accounting rows;
- identify how PAPER and any historic LIVE rows are distinguished;
- snapshot/backup a representative database;
- add/verify a persisted schema version.

A migration must be idempotent and preserve historic P/L exactly.

### 2. Durable logical order intent before network placement

In `execution.py` / database:

- generate a UUID `clientOrderId` before calling Bitvavo;
- persist that logical intent before network I/O;
- persist market, side, requested order type, operatorId and mode;
- use market + Bitvavo `orderId` as exchange identity;
- do not blindly create a second order after an ambiguous timeout.

Required reference behavior:
`execution_contract/`.

### 3. Implement authoritative order/fill lifecycle

Persist and reconcile:

- `new`;
- `awaitingTrigger`;
- `partiallyFilled`;
- `filled`;
- `canceled`;
- `expired`.

Fills are append-only and idempotent by fill ID. A cancel/expire may still have fills.

For timeout error 109: query by `clientOrderId` / authoritative order state before any retry.

### 4. Move accounting to actual settled fills

Accounting must consume:

- actual fill amount;
- actual fill price;
- actual fee;
- `feeCurrency`;
- settlement state.

Do not derive realized P/L from requested amount, target price or configured fee percentage.

Reference:
`accounting_contract/`.

### 5. Restart/reconnect reconciliation gate

On process start or authenticated-stream reconnect:

- enter `RECOVERING`;
- load local persisted intents/orders/fills;
- obtain exchange balances;
- obtain authoritative open order/order/fill state;
- reconcile local vs exchange;
- reject unknown/conflicting state;
- allow no new exchange writes until reconciliation succeeds.

Reference:
`runtime_contract/`.

### 6. PAPER/LIVE isolation

PAPER must never share the authenticated create/update/cancel write path.

Database provenance must distinguish at least:

- replay/backtest;
- PAPER;
- LIVE.

A mode switch must not reinterpret prior simulated fills as real exchange fills.

### 7. LIVE gate

LIVE remains disabled until deterministic tests prove:

- current schema;
- restart reconciliation;
- balance reconciliation;
- no unknown orders;
- no unresolved settlement/fee data;
- fresh market rules;
- fresh authenticated fee schedule;
- market status `trading`;
- read + trade API permissions;
- no withdrawal permission;
- explicit max-order notional;
- explicit total-exposure cap;
- tested kill switch;
- Cancel on disconnect readiness if resting orders can exist.

No strategy result alone enables LIVE.

### 8. Pause / kill switch

Implement these semantics explicitly:

**PAUSED**
- no new/increased exposure;
- may cancel entry orders;
- may maintain/cancel exits;
- may perform a risk-reducing exit.

**SAFE_HALT**
- no new/increased exposure;
- cancel bot-owned open orders;
- risk-reducing exit allowed;
- no hidden automatic full market liquidation.

If resting limit/trigger orders are possible, evaluate Bitvavo `cancelOrdersAfter` / `codGroupId` and heartbeat handling.

### 9. Dashboard

Keep the homepage owner/result focused.

Primary figures:
- deposited;
- withdrawn;
- realized profit;
- current bot value;
- available cash;
- money in market.

Technical recovery/order-state detail belongs under Bot-status / Posities, not on the homepage.

Do not force `available cash + money in market == bot value` when quote funds are reserved in open orders. Reserved `inOrder` funds still need accounting/reconciliation even if not a headline card.

## Required deterministic regression cases

Before LIVE review, production tests must prove at least:

1. ambiguous create timeout does not duplicate an order;
2. duplicate fill delivery is idempotent;
3. partial fill + cancel retains BTC/quote/fee economics;
4. terminal order cannot be resurrected by stale event;
5. cancel race accepts fills that happen before authoritative cancellation;
6. post-only cancellation is handled as a terminal exchange outcome;
7. restart with unknown exchange order blocks placements;
8. restart with balance mismatch blocks placements;
9. withdrawal-enabled API key blocks LIVE;
10. halted/cancel-only market blocks new exposure;
11. market tick/min/max/decimal rules are loaded dynamically;
12. authenticated fee schedule is used instead of hard-coded fee;
13. unsettled fill cannot finalize P/L as if fee were known;
14. migration rerun is safe and historic P/L unchanged;
15. PAPER path cannot invoke authenticated order writes;
16. pause blocks entry while still permitting risk reduction;
17. safe halt does not silently liquidate;
18. resting-order strategy loses LIVE readiness if Cancel on disconnect is required but unavailable/unverified.

## Stop condition

This hardening pass is complete when the existing bot passes the above tests with its real SQLite migration/restart paths **without changing strategy logic**.

After that, wait for research evidence before creating or enabling any new Smart strategy implementation.
