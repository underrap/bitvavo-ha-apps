#!/usr/bin/env python3
"""Portable runtime/PAPER/LIVE safety contract.

Reference/test module only. No network I/O and no trading actions.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class RuntimeState(str,Enum):
    RECOVERING="RECOVERING"
    RUNNING="RUNNING"
    PAUSED="PAUSED"
    SAFE_HALT="SAFE_HALT"
    BLOCKED="BLOCKED"

class Action(str,Enum):
    READ="READ"
    NEW_ENTRY="NEW_ENTRY"
    INCREASE_EXPOSURE="INCREASE_EXPOSURE"
    RISK_REDUCING_EXIT="RISK_REDUCING_EXIT"
    CANCEL_ENTRY="CANCEL_ENTRY"
    CANCEL_EXIT="CANCEL_EXIT"
    UPDATE_ENTRY="UPDATE_ENTRY"
    UPDATE_EXIT="UPDATE_EXIT"

@dataclass(frozen=True)
class LiveGate:
    configured_live: bool
    schema_current: bool
    restart_reconciled: bool
    balances_reconciled: bool
    orders_reconciled: bool
    no_unknown_orders: bool
    no_unsettled_fills: bool
    market_rules_loaded: bool
    fees_loaded: bool
    market_trading: bool
    read_permission: bool
    trade_permission: bool
    withdraw_permission: bool
    exposure_cap_configured: bool
    order_cap_configured: bool
    kill_switch_tested: bool
    resting_orders_possible: bool
    cancel_on_disconnect_ready: bool

    def failures(self) -> list[str]:
        checks={
            "configured_live":self.configured_live,
            "schema_current":self.schema_current,
            "restart_reconciled":self.restart_reconciled,
            "balances_reconciled":self.balances_reconciled,
            "orders_reconciled":self.orders_reconciled,
            "no_unknown_orders":self.no_unknown_orders,
            "no_unsettled_fills":self.no_unsettled_fills,
            "market_rules_loaded":self.market_rules_loaded,
            "fees_loaded":self.fees_loaded,
            "market_trading":self.market_trading,
            "read_permission":self.read_permission,
            "trade_permission":self.trade_permission,
            "withdraw_permission_disabled":not self.withdraw_permission,
            "exposure_cap_configured":self.exposure_cap_configured,
            "order_cap_configured":self.order_cap_configured,
            "kill_switch_tested":self.kill_switch_tested,
            "cancel_on_disconnect_ready":(
                self.cancel_on_disconnect_ready if self.resting_orders_possible else True
            ),
        }
        return [k for k,v in checks.items() if not v]

    @property
    def ready(self) -> bool:
        return not self.failures()

def startup_state(gate: LiveGate, *, configured_mode: str) -> RuntimeState:
    mode=configured_mode.upper()
    if mode=="PAPER":
        return RuntimeState.RUNNING
    if mode!="LIVE":
        return RuntimeState.BLOCKED
    # LIVE never starts by assuming local state is authoritative.
    return RuntimeState.RUNNING if gate.ready else RuntimeState.RECOVERING

def action_allowed(state: RuntimeState, action: Action) -> bool:
    if action==Action.READ:
        return True
    if state==RuntimeState.RUNNING:
        return True
    if state==RuntimeState.RECOVERING:
        return False
    if state==RuntimeState.BLOCKED:
        return False
    if state==RuntimeState.PAUSED:
        # Pause means: no new/increased exposure. Keep ability to reduce risk
        # and cancel entry-side orders. Do not silently abandon existing positions.
        return action in {Action.RISK_REDUCING_EXIT,Action.CANCEL_ENTRY,Action.CANCEL_EXIT,Action.UPDATE_EXIT}
    if state==RuntimeState.SAFE_HALT:
        # Kill switch must fail closed. It never auto-liquidates. Only explicit
        # risk-reducing actions and cancellation of bot-owned orders are allowed.
        return action in {Action.RISK_REDUCING_EXIT,Action.CANCEL_ENTRY,Action.CANCEL_EXIT}
    return False
