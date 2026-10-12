# F0 execution-topology decision — CLOSED

Date: 2026-10-12

## Decision

**BTC/USDC is the preferred execution market for taker-style BTC spot execution at the measured order sizes, provided the bot maintains USDC inventory rather than converting EUR↔USDC on every trade.**

F0 is now closed. This decision does not assert predictive edge and does not justify LIVE trading by itself.

## Evidence

Completed prospective seven-day dataset:
- usable paired depth-100 snapshots: **10,081**
- pre-registered minimum: **>= 8,000 — PASS**
- paired insufficient-depth observations: **0** for BTC/EUR and BTC/USDC across the tested notionals through EUR 10,000
- BTC/USDC cheaper fraction: **1.0** for all displayed tested notionals

Taker/taker round-trip cost, representative measured values:

| EUR-equivalent BTC exposure | BTC/EUR median bp | BTC/USDC median bp | USDC minus EUR median bp |
| ---: | ---: | ---: | ---: |
| 100 | 50.0073 | 12.7194 | -37.2997 |
| 250 | 50.0073 | 12.7349 | -37.2997 |
| 500 | 50.0074 | 12.7569 | -37.2864 |
| 1,000 | 50.0075 | 12.8957 | -37.1596 |
| 2,500 | 50.0079 | 13.2730 | -36.8208 |
| 5,000 | 50.0246 | 13.7600 | -36.3463 |
| 10,000 | 50.1839 | 15.4244 | -34.8280 |

At EUR 500 equivalent, the one-hour block-bootstrap 95% CI for the mean paired delta was approximately **[-37.323, -37.169] bp**, wholly below zero.

Daily EUR-500-equivalent paired mean deltas were negative on every observed day, approximately **-37.58 to -36.61 bp**.

## Important boundary

The primary comparison assumes **steady USDC inventory**. It does not include repeatedly funding and defunding USDC every BTC round trip.

If EUR↔USDC conversion is performed every cycle, conversion fees plus unmeasured conversion spread/slippage/basis reduce the advantage materially. Therefore:
- do not convert EUR→USDC→EUR around every BTC trade;
- treat USDC inventory management as a separate treasury/execution concern;
- measure real conversion economics before LIVE funding decisions.

## Liquidity caveat

Public trade-window audit:
- BTC-EUR unique public trades: **231,839**
- BTC-USDC unique public trades: **8,262**

BTC/USDC therefore showed much lower observed trade activity even though the sampled depth-100 books had enough displayed depth for all tested notionals. The F0 result is strongest for immediate/taker execution-cost topology; it does **not** prove passive-maker fill quality, queue position, or adverse-selection quality on BTC/USDC.

## Project consequence

- Preferred execution venue for future taker-style Smart strategy economics: **BTC/USDC**
- BTC/EUR remains the EUR funding/accounting reference and fallback market.
- F0: **CLOSED**
- Next research decision remains repaired M1A -> M1B only if M1A PASS.
