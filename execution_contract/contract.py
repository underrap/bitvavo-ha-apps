#!/usr/bin/env python3
"""Strategy-independent Bitvavo execution safety contract.

Reference/test module only. It is deliberately not imported by the trading bot
or research executors. The production runtime can be checked against the same
invariants before LIVE is enabled.

Sources (verified 2026-10-03):
- https://docs.bitvavo.com/docs/order-lifecycle/
- https://docs.bitvavo.com/docs/websocket-api/track-your-orders/
- https://docs.bitvavo.com/docs/errors/
- https://docs.bitvavo.com/docs/rest-api/get-markets/
- https://docs.bitvavo.com/docs/rest-api/get-account-fees/
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any
from uuid import UUID

ACTIVE_STATUSES=frozenset({"new","awaitingTrigger","partiallyFilled"})
TERMINAL_STATUSES=frozenset({"filled","canceled","expired"})
ALL_STATUSES=ACTIVE_STATUSES|TERMINAL_STATUSES

# Terminal -> anything is forbidden for authoritative order-state events.
# Active states may legally move to another active state or a terminal state.
ALLOWED_TRANSITIONS={
    None: ALL_STATUSES,
    "new": ALL_STATUSES,
    "awaitingTrigger": ALL_STATUSES,
    "partiallyFilled": ALL_STATUSES,
    "filled": frozenset({"filled"}),
    "canceled": frozenset({"canceled"}),
    "expired": frozenset({"expired"}),
}

class RetryAction(str,Enum):
    NO_RETRY="NO_RETRY"
    RETRY_BACKOFF="RETRY_BACKOFF"
    WAIT_RATE_LIMIT="WAIT_RATE_LIMIT"
    WAIT_MARKET_TRADING="WAIT_MARKET_TRADING"
    VERIFY_STATE_BEFORE_RETRY="VERIFY_STATE_BEFORE_RETRY"

def D(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError):
        raise ValueError(f"not a decimal: {value!r}")

def require_uuid(value: str, field_name: str) -> str:
    try:
        UUID(str(value))
    except Exception:
        raise ValueError(f"{field_name} must be UUID: {value!r}")
    return str(value)

def retry_action(http_status: int, error_code: int | None=None) -> RetryAction:
    """Map documented Bitvavo errors to a safe retry posture."""
    if error_code==109:
        # Operation may or may not have succeeded: query authoritative state first.
        return RetryAction.VERIFY_STATE_BEFORE_RETRY
    if http_status==429:
        return RetryAction.WAIT_RATE_LIMIT
    if http_status==409:
        return RetryAction.WAIT_MARKET_TRADING
    if http_status in (500,503):
        return RetryAction.RETRY_BACKOFF
    return RetryAction.NO_RETRY

@dataclass(frozen=True)
class MarketRules:
    market: str
    status: str
    min_base: Decimal
    min_quote: Decimal
    max_base: Decimal
    max_quote: Decimal
    quantity_decimals: int
    notional_decimals: int
    tick_size: Decimal
    max_open_orders: int

    @classmethod
    def from_api(cls,x: dict[str,Any]) -> "MarketRules":
        return cls(
            market=str(x["market"]),
            status=str(x["status"]),
            min_base=D(x["minOrderInBaseAsset"]),
            min_quote=D(x["minOrderInQuoteAsset"]),
            max_base=D(x["maxOrderInBaseAsset"]),
            max_quote=D(x["maxOrderInQuoteAsset"]),
            quantity_decimals=int(x["quantityDecimals"]),
            notional_decimals=int(x["notionalDecimals"]),
            tick_size=D(x["tickSize"]),
            max_open_orders=int(x["maxOpenOrders"]),
        )

    def validate_new_order(self, *, amount: Decimal|None=None,
                           amount_quote: Decimal|None=None,
                           price: Decimal|None=None) -> None:
        if self.status!="trading":
            raise ValueError(f"{self.market}: market status is {self.status!r}, not trading")
        if amount is None and amount_quote is None:
            raise ValueError("amount or amountQuote required")
        if amount is not None:
            amount=D(amount)
            if amount<self.min_base or amount>self.max_base:
                raise ValueError("amount outside market base bounds")
            if -amount.as_tuple().exponent>self.quantity_decimals:
                raise ValueError("amount exceeds quantityDecimals")
        if amount_quote is not None:
            amount_quote=D(amount_quote)
            if amount_quote<self.min_quote or amount_quote>self.max_quote:
                raise ValueError("amountQuote outside market quote bounds")
            if -amount_quote.as_tuple().exponent>self.notional_decimals:
                raise ValueError("amountQuote exceeds notionalDecimals")
        if price is not None:
            price=D(price)
            if price<=0 or self.tick_size<=0 or price%self.tick_size!=0:
                raise ValueError("price is not a positive multiple of tickSize")

@dataclass
class Fill:
    fill_id: str
    amount: Decimal
    price: Decimal
    fee: Decimal
    fee_currency: str
    taker: bool
    timestamp_ms: int

@dataclass
class OrderLedger:
    """Append-only local view for one (market, clientOrderId) intent."""
    market: str
    client_order_id: str
    operator_id: int
    order_id: str|None=None
    status: str|None=None
    side: str|None=None
    order_type: str|None=None
    amount: Decimal|None=None
    amount_remaining: Decimal|None=None
    filled_amount: Decimal=Decimal("0")
    filled_amount_quote: Decimal=Decimal("0")
    updated_ns: int|None=None
    fills: dict[str,Fill]=field(default_factory=dict)
    fees_by_currency: dict[str,Decimal]=field(default_factory=dict)

    def __post_init__(self):
        require_uuid(self.client_order_id,"clientOrderId")
        if not isinstance(self.operator_id,int) or self.operator_id<0:
            raise ValueError("operatorId must be a non-negative integer")

    @property
    def key(self):
        # Bitvavo orderId is unique per market, not globally.
        return (self.market,self.order_id) if self.order_id else (self.market,self.client_order_id)

    def bind_order_id(self, order_id: str) -> None:
        require_uuid(order_id,"orderId")
        if self.order_id is not None and self.order_id!=order_id:
            raise ValueError("orderId changed for an existing clientOrderId")
        self.order_id=order_id

    def apply_order_event(self,e: dict[str,Any]) -> None:
        if str(e.get("market"))!=self.market:
            raise ValueError("market mismatch")
        coid=e.get("clientOrderId")
        if coid is not None and str(coid)!=self.client_order_id:
            raise ValueError("clientOrderId mismatch")
        if e.get("operatorId") is not None and int(e["operatorId"])!=self.operator_id:
            raise ValueError("operatorId mismatch")
        if e.get("orderId") is not None:
            self.bind_order_id(str(e["orderId"]))

        new_status=str(e["status"])
        if new_status not in ALL_STATUSES:
            raise ValueError(f"unknown order status: {new_status}")
        if new_status not in ALLOWED_TRANSITIONS[self.status]:
            raise ValueError(f"illegal terminal transition {self.status!r} -> {new_status!r}")

        updated_ns=e.get("updatedNs")
        if updated_ns is not None:
            updated_ns=int(updated_ns)
            if self.updated_ns is not None and updated_ns<self.updated_ns:
                raise ValueError("stale order event: updatedNs regressed")
            self.updated_ns=updated_ns

        if e.get("side") is not None:
            side=str(e["side"])
            if side not in ("buy","sell"): raise ValueError("invalid side")
            if self.side is not None and self.side!=side: raise ValueError("side changed")
            self.side=side
        if e.get("orderType") is not None:
            if self.order_type is not None and self.order_type!=str(e["orderType"]):
                raise ValueError("orderType changed")
            self.order_type=str(e["orderType"])

        if e.get("amount") is not None:
            amount=D(e["amount"])
            if amount<0: raise ValueError("negative amount")
            if self.amount is not None and self.amount!=amount:
                raise ValueError("original order amount changed")
            self.amount=amount

        if e.get("amountRemaining") is not None:
            rem=D(e["amountRemaining"])
            if rem<0: raise ValueError("negative amountRemaining")
            self.amount_remaining=rem

        if e.get("filledAmount") is not None:
            fa=D(e["filledAmount"])
            if fa<self.filled_amount:
                raise ValueError("filledAmount regressed")
            self.filled_amount=fa
        if e.get("filledAmountQuote") is not None:
            fq=D(e["filledAmountQuote"])
            if fq<self.filled_amount_quote:
                raise ValueError("filledAmountQuote regressed")
            self.filled_amount_quote=fq

        self.status=new_status
        self._check_invariants()

    def apply_fill_event(self,e: dict[str,Any]) -> bool:
        if str(e.get("market"))!=self.market:
            raise ValueError("market mismatch")
        if self.order_id is not None and str(e.get("orderId"))!=self.order_id:
            raise ValueError("orderId mismatch")
        if e.get("clientOrderId") is not None and str(e["clientOrderId"])!=self.client_order_id:
            raise ValueError("clientOrderId mismatch")
        fid=str(e["fillId"])
        if fid in self.fills:
            return False  # idempotent duplicate delivery

        f=Fill(
            fill_id=fid,
            amount=D(e["amount"]),
            price=D(e["price"]),
            fee=D(e.get("fee","0")),
            fee_currency=str(e.get("feeCurrency","")),
            taker=bool(e["taker"]),
            timestamp_ms=int(e["timestamp"]),
        )
        if f.amount<=0 or f.price<=0:
            raise ValueError("fill amount/price must be positive")
        self.fills[fid]=f
        self.fees_by_currency[f.fee_currency]=self.fees_by_currency.get(f.fee_currency,Decimal("0"))+f.fee
        return True

    def _check_invariants(self) -> None:
        if self.amount is not None and self.amount_remaining is not None:
            if self.amount_remaining>self.amount:
                raise ValueError("amountRemaining exceeds amount")
        if self.amount is not None and self.filled_amount>self.amount:
            raise ValueError("filledAmount exceeds amount")
        if self.status=="filled" and self.amount_remaining not in (None,Decimal("0")):
            raise ValueError("filled order has nonzero amountRemaining")
        # canceled/expired may legitimately be partially filled. Never zero fills/P&L on terminal cancel.

def restart_reconciliation_required(local_orders: list[OrderLedger]) -> bool:
    """Any nonterminal or unbound intent requires authoritative reconciliation before placing new orders."""
    return any(o.order_id is None or o.status not in TERMINAL_STATUSES for o in local_orders)

def live_key_permissions_ok(*,read_only: bool, trade: bool, withdraw: bool) -> bool:
    """LIVE bot key should read + trade but must not have withdrawal permission."""
    return bool(read_only and trade and not withdraw)
