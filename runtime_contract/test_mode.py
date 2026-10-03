from pathlib import Path
import sys
BASE=Path(__file__).parent
sys.path.insert(0,str(BASE))
from mode import *

def good_gate(**overrides):
    d=dict(
        configured_live=True,schema_current=True,restart_reconciled=True,
        balances_reconciled=True,orders_reconciled=True,no_unknown_orders=True,
        no_unsettled_fills=True,market_rules_loaded=True,fees_loaded=True,
        market_trading=True,read_permission=True,trade_permission=True,
        withdraw_permission=False,exposure_cap_configured=True,
        order_cap_configured=True,kill_switch_tested=True,
        resting_orders_possible=True,cancel_on_disconnect_ready=True,
        private_order_stream_ready=True,continuous_reconciliation_ready=True,
    )
    d.update(overrides)
    return LiveGate(**d)

g=good_gate()
assert g.ready
assert startup_state(g,configured_mode="LIVE")==RuntimeState.RUNNING
assert startup_state(g,configured_mode="PAPER")==RuntimeState.RUNNING

# Every critical LIVE gate fails closed.
for field in (
    "schema_current","restart_reconciled","balances_reconciled","orders_reconciled",
    "no_unknown_orders","no_unsettled_fills","market_rules_loaded","fees_loaded",
    "market_trading","read_permission","trade_permission","exposure_cap_configured",
    "order_cap_configured","kill_switch_tested","cancel_on_disconnect_ready",
    "private_order_stream_ready","continuous_reconciliation_ready",
):
    bad=good_gate(**{field:False})
    assert not bad.ready,(field,bad.failures())
    assert startup_state(bad,configured_mode="LIVE")==RuntimeState.RECOVERING

# Cancel-on-disconnect is conditionally required only when resting orders can exist.
assert good_gate(resting_orders_possible=False,cancel_on_disconnect_ready=False).ready
bad_cod=good_gate(resting_orders_possible=True,cancel_on_disconnect_ready=False)
assert not bad_cod.ready
assert "cancel_on_disconnect_ready" in bad_cod.failures()

bad=good_gate(withdraw_permission=True)
assert not bad.ready
assert "withdraw_permission_disabled" in bad.failures()

# PAUSED and SAFE_HALT never increase exposure.
for s in (RuntimeState.PAUSED,RuntimeState.SAFE_HALT):
    assert not action_allowed(s,Action.NEW_ENTRY)
    assert not action_allowed(s,Action.INCREASE_EXPOSURE)
    assert action_allowed(s,Action.READ)
    assert action_allowed(s,Action.RISK_REDUCING_EXIT)
    assert action_allowed(s,Action.CANCEL_ENTRY)
    assert action_allowed(s,Action.CANCEL_EXIT)

assert action_allowed(RuntimeState.PAUSED,Action.UPDATE_EXIT)
assert not action_allowed(RuntimeState.SAFE_HALT,Action.UPDATE_EXIT)

# During recovery no exchange write is permitted.
for a in Action:
    if a==Action.READ: assert action_allowed(RuntimeState.RECOVERING,a)
    else: assert not action_allowed(RuntimeState.RECOVERING,a)

print("Runtime LIVE-safety contract PASS")
