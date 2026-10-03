# Public trading-engine benchmark for safety contracts

Reviewed 2026-10-03. Purpose: challenge the project-specific execution/accounting/runtime
contracts against mature public implementations instead of relying only on first-principles
design and Bitvavo's API documentation.

## Systems reviewed

### NautilusTrader

Relevant public behavior:
- startup reconciliation aligns cached order/position state with venue reports;
- missed fills are reconstructed from authoritative venue reports;
- duplicate fill IDs are detected;
- partially-filled then canceled orders preserve their fill history;
- external/unknown venue orders are surfaced explicitly;
- continuous reconciliation runs after startup, checking in-flight orders, open orders and
  position status.

Sources:
- https://nautilustrader.io/docs/latest/concepts/execution/reconciliation/
- https://nautilustrader.io/docs/latest/concepts/execution/
- https://nautilustrader.io/docs/latest/concepts/execution/policies/

### Hummingbot

Relevant public behavior:
- client-side order ID is returned/created before exchange submission and tracking starts before
  the API placement request;
- InFlightOrder / ClientOrderTracker retain active order state;
- private user streams carry order/balance updates;
- connector QA explicitly tests reconnect recovery, filled-order tracking and graceful cancellation.

Sources:
- https://hummingbot.org/connectors/connectors/architecture/
- https://hummingbot.org/connectors/connectors/architecture/order_lifecycle/
- https://hummingbot.org/connectors/connectors/test/

### Freqtrade

Relevant public behavior:
- trade/order objects are persisted;
- order records retain exchange order ID, requested and actual fill values, remaining quantity,
  average price and fee information;
- the live bot loop repeatedly updates open-order state from the exchange and handles filled
  orders/timeouts;
- dry-run/live execution is an explicit operating distinction.

Sources:
- https://docs.freqtrade.io/en/stable/bot-basics/
- https://docs.freqtrade.io/en/stable/trade-object/

## Result of the benchmark

The existing Bitvavo contracts were directionally aligned with all three on the important
foundations:
- persist intent/order state before relying on network acknowledgement;
- track partial fills and terminal order state separately;
- deduplicate fills;
- reconcile local state to venue state;
- account from actual fills/fees;
- isolate PAPER from LIVE;
- fail closed when execution state is uncertain.

The benchmark exposed one material omission in our first draft:

**Continuous reconciliation was underspecified.**

Our contract covered startup/reconnect reconciliation, but did not explicitly require ongoing
runtime checks after startup. NautilusTrader makes this a first-class subsystem, Hummingbot's
tracker/QA expects recovery of open orders after connectivity problems, and Freqtrade repeatedly
refreshes open-order state from the exchange.

That gap is now promoted to a LIVE requirement in `runtime_contract/`:
- authenticated order/fill stream ready;
- periodic authoritative reconciliation ready;
- unresolved discrepancy blocks new exposure.

## Deliberate non-copying

These frameworks are references, not templates. We do not import their architecture wholesale.
Their complexity reflects multi-exchange/multi-strategy products. The Bitvavo bot should keep the
smallest design that satisfies the same failure-mode protections relevant to one spot venue.

The Bitvavo API remains authoritative for venue-specific behavior such as:
- documented order statuses;
- error code 109 ambiguity;
- operatorId;
- market/tick/min/max rules;
- Cancel on disconnect;
- authenticated fee and balance semantics.
