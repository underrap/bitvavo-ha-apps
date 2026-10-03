# Spot accounting safety contract

Status: **reference/test contract — no runtime dependency**

This contract captures accounting invariants that remain useful regardless of which
strategy survives Edge Discovery. It is intended to be mirrored by the local
production bot before LIVE is enabled.

## Core rules

- Use decimal arithmetic for money, quantity, prices and fees.
- A fill is applied exactly once, keyed by fill ID.
- Only settled fills may finalize accounting. Bitvavo documents that an unsettled
  fill may not yet include the fee and the exchanged currency is not yet available
  for further trading.
- Fees are taken from the actual fill payload and its `feeCurrency`; do not infer
  them from a configured percentage after execution.
- Deposits and withdrawals are owner cash flows, not trading profit/loss.
- A canceled or expired order can retain already executed fills; accounting is fill
  driven, not final-order-status driven.
- The reference oracle is long-only and uses weighted-average cost. This is not a
  strategy choice; it is an accounting convention for deterministic realized P/L.
- If a fee is charged in base currency, it changes net base inventory. If charged in
  quote currency, it changes quote cash/proceeds.
- A fee in a third currency must fail closed unless it has an explicit valuation.
- On restart, local accounted balances must reconcile against exchange
  `available + inOrder` balances within configured tolerances before new orders.

## Owner-facing identities

For a EUR-funded BTC spot bot:

`current bot value = accounted quote cash + BTC position × mark price`

`owner total result = current bot value + cumulative withdrawals - cumulative deposits`

This prevents deposits from masquerading as profit and withdrawals from masquerading
as losses.

The homepage may show:
- deposited;
- withdrawn;
- realized profit;
- current bot value;
- available cash;
- money in the market.

Open-order reservations must still be accounted for technically. A production
dashboard should not force `available cash + money in market = current bot value`
when quote cash is reserved in open orders; reserved funds belong in reconciliation
even if they are not a primary homepage card.

## Source facts

Verified 2026-10-03 against:
- https://docs.bitvavo.com/docs/rest-api/get-order/
- https://docs.bitvavo.com/docs/rest-api/get-trade-history/
- https://docs.bitvavo.com/docs/websocket-api/track-your-orders/
- https://docs.bitvavo.com/docs/websocket-api/get-account-balance/

The production source of truth remains the local Bitvavo Trading Bot workspace.
