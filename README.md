# bitvavo-ha-apps

Home Assistant add-ons and portable conformance contracts used by the Bitvavo Trading Bot project.

## Repository boundary

This repository is **not** the production trading bot.

The production source of truth remains the local **Bitvavo Trading Bot** workspace used by the bot-development workflow. Nothing in this repository should become a mandatory runtime dependency of that bot.

This repository contains:

- `bitvavo_event_m0/` — public, research-only event-level BTC-EUR/BTC-USDC collector;
- `bitvavo_microstructure/` — public 7-day BTC/EUR ↔ BTC/USDC execution-topology collector plus the F0 analyzer and safe handoff packager;
- `bitvavo_m1a/` — frozen M1A same-venue microstructure information test and provenance gate;
- `execution_contract/` — portable order-lifecycle, restart/reconciliation and LIVE-safety reference contract;
- `accounting_contract/` — portable fill/accounting and owner-metric reference contract.

## Safety boundary

Research collectors and analyzers:

- use public market data only;
- do not require Bitvavo API keys;
- do not place, update or cancel orders;
- do not read or modify the production bot database;
- do not enable LIVE trading.

The execution/accounting contract modules are deterministic test oracles only. They contain no Bitvavo credentials and perform no network trading actions.

## Current research gates

- **F0:** wait for the prospective seven-day collector to finish; analyze only the completed, manifest-consistent handoff bundle.
- **M1A:** protocol = `M1A-PREREG-v1.3`; executor v1.2.0; execute only after `M1A_FREEZE_001` provenance passes.
- No new strategy implementation is justified by these infrastructure modules themselves.

## Production integration rule

Any future runtime change in the local bot must separately verify:

- database migrations;
- order states and partial fills;
- actual fill fees;
- accounting;
- restart/recovery reconciliation;
- PAPER/LIVE separation;
- LIVE safety.

The portable contracts in this repository are intended to make those checks reproducible without coupling research code to production.
