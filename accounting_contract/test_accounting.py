from decimal import Decimal
from pathlib import Path
import sys
BASE=Path(__file__).parent
sys.path.insert(0,str(BASE))
from accounting import SpotAccounting,FillInput,reconcile_balances

a=SpotAccounting()
a.deposit_quote("500")
m=a.mark_to_market("50000")
assert m["current_bot_value"]==Decimal("500")
assert m["owner_total_result"]==Decimal("0")

# Buy 0.001 BTC @ 50k with EUR fee.
f1=FillInput.make(fill_id="f1",side="buy",amount="0.001",price="50000",fee="0.125",fee_currency="EUR")
assert a.apply_fill(f1)
assert not a.apply_fill(f1)
assert a.s.base_position==Decimal("0.001")
assert a.s.quote_cash_delta==Decimal("449.875")
assert a.s.average_cost_quote_per_base==Decimal("50125")

# Mark price up: unrealized P/L separated from deposits.
m=a.mark_to_market("51000")
assert m["money_in_market"]==Decimal("51.000")
assert m["current_bot_value"]==Decimal("500.875")
assert m["owner_total_result"]==Decimal("0.875")
assert m["realized_pnl"]==Decimal("0")
assert m["unrealized_pnl"]==Decimal("0.875")

# Partial sell; quote fee reduces proceeds and realized result.
f2=FillInput.make(fill_id="f2",side="sell",amount="0.0004",price="52000",fee="0.052",fee_currency="EUR")
a.apply_fill(f2)
assert a.s.base_position==Decimal("0.0006")
assert a.s.realized_pnl_quote==Decimal("0.698")

# Buy fee in base reduces received inventory and changes effective cost basis.
b=SpotAccounting();b.deposit_quote("100")
b.apply_fill(FillInput.make(fill_id="b1",side="buy",amount="0.001",price="50000",fee="0.000001",fee_currency="BTC"))
assert b.s.base_position==Decimal("0.000999")
assert b.s.quote_cash_delta==Decimal("50.000")
assert b.s.average_cost_quote_per_base>Decimal("50000")

# Sell fee in base consumes inventory in addition to sold amount.
before=b.s.base_position
b.apply_fill(FillInput.make(fill_id="b2",side="sell",amount="0.0005",price="51000",fee="0.000001",fee_currency="BTC"))
assert b.s.base_position==before-Decimal("0.000501")

# Unsettled fills cannot finalize economics because fee may still be absent.
try:
    a.apply_fill(FillInput.make(fill_id="u1",side="buy",amount="0.0001",price="50000",settled=False))
    raise AssertionError("unsettled fill accepted")
except ValueError: pass

# Owner withdrawal is not a trading loss.
before=a.mark_to_market("50000")["owner_total_result"]
a.withdraw_quote("10")
after=a.mark_to_market("50000")["owner_total_result"]
assert before==after

# Exchange reconciliation includes inOrder reserves.
r=reconcile_balances(
    accounted_quote="100",accounted_base="0.01",
    exchange_quote_available="80",exchange_quote_in_order="20",
    exchange_base_available="0.009",exchange_base_in_order="0.001"
)
assert r["ok"]

r2=reconcile_balances(
    accounted_quote="100",accounted_base="0.01",
    exchange_quote_available="79",exchange_quote_in_order="20",
    exchange_base_available="0.009",exchange_base_in_order="0.001"
)
assert not r2["ok"]

print("Accounting safety contract PASS")
