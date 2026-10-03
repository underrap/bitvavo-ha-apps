import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
BASE=Path(__file__).parent
sys.path.insert(0,str(BASE))
from contract import *

def uid(): return str(uuid4())

# API retry policy: ambiguous timeout must never be blindly replayed.
assert retry_action(503,109)==RetryAction.VERIFY_STATE_BEFORE_RETRY
assert retry_action(429)==RetryAction.WAIT_RATE_LIMIT
assert retry_action(409)==RetryAction.WAIT_MARKET_TRADING
assert retry_action(503,111)==RetryAction.RETRY_BACKOFF
assert retry_action(400)==RetryAction.NO_RETRY

rules=MarketRules.from_api({
    "market":"BTC-EUR","status":"trading",
    "minOrderInBaseAsset":"0.0001","minOrderInQuoteAsset":"5",
    "maxOrderInBaseAsset":"100","maxOrderInQuoteAsset":"1000000",
    "quantityDecimals":8,"notionalDecimals":2,"tickSize":"0.01","maxOpenOrders":100
})
rules.validate_new_order(amount_quote=Decimal("50.00"))
rules.validate_new_order(amount=Decimal("0.00100000"),price=Decimal("50000.01"))
for kwargs in (
    {"amount_quote":Decimal("4.99")},
    {"amount":Decimal("0.00001")},
    {"amount":Decimal("0.001000001")},
    {"amount":Decimal("0.001"),"price":Decimal("50000.005")},
):
    try: rules.validate_new_order(**kwargs); raise AssertionError(kwargs)
    except ValueError: pass

halted=MarketRules(**{**rules.__dict__,"status":"halted"})
try: halted.validate_new_order(amount_quote=Decimal("50")); raise AssertionError("halted accepted")
except ValueError: pass

coid=uid(); oid=uid()
o=OrderLedger("BTC-EUR",coid,42)
assert restart_reconciliation_required([o])
o.apply_order_event({
    "event":"order","market":"BTC-EUR","clientOrderId":coid,"orderId":oid,"operatorId":42,
    "status":"new","side":"buy","orderType":"limit","amount":"0.002","amountRemaining":"0.002",
    "filledAmount":"0","filledAmountQuote":"0","updatedNs":100
})
o.apply_order_event({
    "event":"order","market":"BTC-EUR","clientOrderId":coid,"orderId":oid,"operatorId":42,
    "status":"partiallyFilled","amount":"0.002","amountRemaining":"0.001",
    "filledAmount":"0.001","filledAmountQuote":"50","updatedNs":200
})
fill={"event":"fill","market":"BTC-EUR","clientOrderId":coid,"orderId":oid,"fillId":uid(),
      "timestamp":1,"amount":"0.001","price":"50000","taker":True,"fee":"0.125","feeCurrency":"EUR"}
assert o.apply_fill_event(fill) is True
assert o.apply_fill_event(fill) is False
assert o.fees_by_currency["EUR"]==Decimal("0.125")

# Partial fill followed by cancellation keeps the executed fill/accounting.
o.apply_order_event({
    "event":"order","market":"BTC-EUR","clientOrderId":coid,"orderId":oid,"operatorId":42,
    "status":"canceled","amount":"0.002","amountRemaining":"0.001",
    "filledAmount":"0.001","filledAmountQuote":"50","updatedNs":300,
    "restatementReason":"cancelPostOnly"
})
assert o.status=="canceled"
assert o.filled_amount==Decimal("0.001")
assert len(o.fills)==1
assert restart_reconciliation_required([o]) is False

# Terminal state cannot be resurrected.
try:
    o.apply_order_event({
        "market":"BTC-EUR","clientOrderId":coid,"orderId":oid,"operatorId":42,
        "status":"new","amount":"0.002","amountRemaining":"0.001",
        "filledAmount":"0.001","filledAmountQuote":"50","updatedNs":400
    })
    raise AssertionError("terminal order resurrected")
except ValueError: pass

# Stale order event rejected.
o2=OrderLedger("BTC-EUR",uid(),42)
oid2=uid()
o2.apply_order_event({"market":"BTC-EUR","clientOrderId":o2.client_order_id,"orderId":oid2,
                      "operatorId":42,"status":"new","updatedNs":200})
try:
    o2.apply_order_event({"market":"BTC-EUR","clientOrderId":o2.client_order_id,"orderId":oid2,
                          "operatorId":42,"status":"new","updatedNs":199})
    raise AssertionError("stale event accepted")
except ValueError: pass

# Filled must not carry an open remainder.
o3=OrderLedger("BTC-EUR",uid(),42)
try:
    o3.apply_order_event({"market":"BTC-EUR","clientOrderId":o3.client_order_id,"orderId":uid(),
                          "operatorId":42,"status":"filled","amount":"1","amountRemaining":"0.1",
                          "filledAmount":"0.9","updatedNs":1})
    raise AssertionError("invalid filled remainder accepted")
except ValueError: pass

# Market+orderId is the identity boundary.
shared=uid()
a=OrderLedger("BTC-EUR",uid(),42); a.bind_order_id(shared)
b=OrderLedger("BTC-USDC",uid(),42); b.bind_order_id(shared)
assert a.key!=b.key

# Key permissions: no withdrawals.
assert live_key_permissions_ok(read_only=True,trade=True,withdraw=False)
assert not live_key_permissions_ok(read_only=True,trade=True,withdraw=True)
assert not live_key_permissions_ok(read_only=True,trade=False,withdraw=False)

print("Execution safety contract PASS")
