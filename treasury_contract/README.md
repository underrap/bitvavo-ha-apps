# BTC/USDC treasury safety contract

Status: **reference/test contract — no runtime dependency**

F0 selected BTC/USDC as the preferred future taker-style execution market when USDC working inventory is retained.

Core invariants:

- treasury funding is separate from BTC strategy entry/exit logic;
- a BTC trade cycle may not trigger EUR<->USDC conversion;
- USDC working inventory uses explicit min/target/max thresholds;
- a single conversion has an explicit EUR notional cap;
- pending funding and `inOrder` USDC count toward working inventory;
- automatic defunding is disabled unless explicitly configured;
- USDC/EUR valuation is explicit; no parity assumption;
- conversion fees/costs are treasury economics, not BTC trading realized P/L;
- production LIVE remains blocked until treasury reconciliation, owner FX valuation and funding policy are ready.

The contract deliberately chooses no numeric production thresholds. Those belong in production configuration and must be set before LIVE review.

This is not a strategy and it performs no network I/O.
