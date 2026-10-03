# Bitvavo execution & LIVE-safety contract

Status: **reference/test contract — no runtime dependency**

This directory defines strategy-independent invariants that the local production bot
(`execution.py` / `bot.py`) must satisfy before any Smart strategy can be enabled for LIVE.
It intentionally does **not** contain strategy logic and must not become a research-result dependency.

## Authoritative API facts

Verified against Bitvavo API documentation on 2026-10-03:

- Order statuses are `new`, `awaitingTrigger`, `partiallyFilled`, `filled`, `canceled`, and `expired`.
- Partial fills must be tracked; canceled or expired orders may already have executed fills.
- Bitvavo recommends the authenticated account WebSocket channel for real-time order/fill tracking.
- REST order lookup/open-orders is the recovery/reconciliation source when reconnecting or restarting.
- An `orderId` is unique per **market**, not globally. Local identity must therefore include the market.
- A client-supplied `clientOrderId` is a UUID and should identify one logical placement intent.
- `operatorId` is required for create/update/cancel and should identify this bot.
- Error code 109 is ambiguous: an operation may or may not have succeeded. State must be checked before retrying; blind create retries can duplicate orders.
- `postOnly=true` can result in a canceled order if it would execute immediately. Cancellation reasons are meaningful data, not generic failures.
- Market metadata supplies current `tickSize`, decimal precision, min/max notional and max open orders; those must be validated at runtime.
- Fees must come from the authenticated fee endpoint for the active market/quote rather than a hard-coded percentage.
- API keys used by the bot must have read + trade permissions and **no withdrawal permission**.
- Bitvavo's Cancel on disconnect can group resting orders under a `codGroupId` and cancel them
  if the bot stops refreshing the countdown; canceled orders report `cancelOnDisconnect`.

Sources:
- https://docs.bitvavo.com/docs/order-lifecycle/
- https://docs.bitvavo.com/docs/websocket-api/track-your-orders/
- https://docs.bitvavo.com/docs/errors/
- https://docs.bitvavo.com/docs/rest-api/create-order/
- https://docs.bitvavo.com/docs/rest-api/get-order/
- https://docs.bitvavo.com/docs/rest-api/get-markets/
- https://docs.bitvavo.com/docs/rest-api/get-account-fees/
- https://docs.bitvavo.com/docs/get-started/
- https://docs.bitvavo.com/docs/cancel-on-disconnect/

## Required production behavior

Before LIVE can be considered, the runtime must demonstrate all of the following with deterministic tests:

1. **Idempotent intent identity** — generate/persist `clientOrderId` before network placement. An ambiguous timeout never creates a second logical order until the first ID has been reconciled.
2. **Authoritative restart recovery** — on startup/reconnect, block new placements; fetch/open-stream authoritative state; reconcile local open intents, fills, reserved balance and terminal states; only then resume.
3. **Append-only fills** — deduplicate by fill ID. Partial fill + cancel/expire retains executed BTC, quote amount and fees.
4. **Terminal monotonicity** — once an authoritative order is filled/canceled/expired, later stale order-state events may not resurrect it.
5. **Cancellation race safety** — cancel requested is not equivalent to canceled. New fills arriving before authoritative cancellation still count.
6. **Accounting from fills** — realized P/L and position quantity derive from settled fills and their actual fees, not requested order amount or quoted target price.
7. **Dynamic fee/market rules** — use current authenticated fee schedule and market metadata; fail closed on unknown market status/rules.
8. **Balance reconciliation** — distinguish `available` from `inOrder`; local “cash available” may not exceed exchange-authoritative spendable balance in LIVE.
9. **Post-only semantics** — `cancelPostOnly`/protection cancellation is an expected terminal outcome, not proof that placement never happened.
10. **Permission safety** — LIVE startup refuses keys with withdrawal permission and refuses missing read/trade permissions.
11. **Self-trade protection** — do not assume simultaneous opposing bot orders can match; persist/handle the selected Bitvavo self-trade-prevention behavior.
12. **Disconnect safety** — if LIVE can leave resting orders, use/test `codGroupId` + Cancel on disconnect or explicitly document why it is not applicable. It supplements, not replaces, restart reconciliation.
13. **Fail closed** — unknown order status, regressing fill totals, conflicting IDs or unreconciled startup state block further placements.

## Integration boundary

The current source of truth for the production bot remains the local **Bitvavo Trading Bot**
workspace. This contract is only a portable acceptance oracle. When the production source is
available in the bot-development workflow, its order/accounting/recovery tests should import or
mirror these cases. Do **not** make `bitvavo-ha-apps` a runtime dependency of the trading bot.
