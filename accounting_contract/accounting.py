#!/usr/bin/env python3
"""Strategy-independent spot accounting contract for Bitvavo.

Reference/test module only. Uses Decimal and settled fill data. Designed to
validate production accounting behavior before LIVE is enabled.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

def D(x: Any) -> Decimal:
    try:
        return Decimal(str(x))
    except (InvalidOperation,TypeError,ValueError):
        raise ValueError(f"not a decimal: {x!r}")

@dataclass(frozen=True)
class FillInput:
    fill_id: str
    side: str
    amount_base: Decimal
    price_quote: Decimal
    fee: Decimal
    fee_currency: str
    settled: bool=True

    @classmethod
    def make(cls, *, fill_id: str, side: str, amount: Any, price: Any,
             fee: Any="0", fee_currency: str="EUR", settled: bool=True):
        if side not in ("buy","sell"):
            raise ValueError("side must be buy or sell")
        a,p,f=D(amount),D(price),D(fee)
        if a<=0 or p<=0:
            raise ValueError("amount and price must be positive")
        return cls(str(fill_id),side,a,p,f,str(fee_currency),bool(settled))

@dataclass
class AccountingState:
    base_symbol: str="BTC"
    quote_symbol: str="EUR"
    base_position: Decimal=Decimal("0")
    quote_cash_delta: Decimal=Decimal("0")
    average_cost_quote_per_base: Decimal=Decimal("0")
    realized_pnl_quote: Decimal=Decimal("0")
    trading_fees_quote_effect: Decimal=Decimal("0")
    deposits_quote: Decimal=Decimal("0")
    withdrawals_quote: Decimal=Decimal("0")

class SpotAccounting:
    """Weighted-average long-only accounting.

    This is an accounting oracle, not a strategy. It records only settled fills.
    It intentionally separates owner cash flows (deposits/withdrawals) from
    trading P/L.
    """
    def __init__(self, base_symbol="BTC", quote_symbol="EUR"):
        self.s=AccountingState(base_symbol=base_symbol,quote_symbol=quote_symbol)
        self._fill_ids=set()

    def deposit_quote(self, amount: Any) -> None:
        v=D(amount)
        if v<=0: raise ValueError("deposit must be positive")
        self.s.deposits_quote += v
        self.s.quote_cash_delta += v

    def withdraw_quote(self, amount: Any) -> None:
        v=D(amount)
        if v<=0: raise ValueError("withdrawal must be positive")
        if v>self.s.quote_cash_delta:
            raise ValueError("withdrawal exceeds accounted quote cash")
        self.s.withdrawals_quote += v
        self.s.quote_cash_delta -= v

    def apply_fill(self, f: FillInput) -> bool:
        if f.fill_id in self._fill_ids:
            return False
        if not f.settled:
            raise ValueError("unsettled fill cannot finalize accounting")
        if f.fee_currency not in (self.s.base_symbol,self.s.quote_symbol):
            raise ValueError("fee in unsupported third currency requires explicit valuation")

        base_fee = f.fee if f.fee_currency==self.s.base_symbol else Decimal("0")
        quote_fee = f.fee if f.fee_currency==self.s.quote_symbol else Decimal("0")

        if f.side=="buy":
            gross_base=f.amount_base
            net_base=gross_base-base_fee
            if net_base<=0:
                raise ValueError("buy fee consumes acquired base")
            gross_quote=gross_base*f.price_quote
            quote_out=gross_quote+quote_fee
            if self.s.quote_cash_delta < quote_out:
                raise ValueError("insufficient accounted quote cash for buy")
            old_cost=self.s.base_position*self.s.average_cost_quote_per_base
            self.s.quote_cash_delta -= quote_out
            self.s.base_position += net_base
            self.s.average_cost_quote_per_base=(old_cost+quote_out)/self.s.base_position
            self.s.trading_fees_quote_effect += quote_fee
        else:
            gross_base=f.amount_base
            inventory_reduction=gross_base+base_fee
            if inventory_reduction<=0:
                raise ValueError("invalid sell inventory reduction")
            if inventory_reduction>self.s.base_position:
                raise ValueError("sell exceeds accounted base position")
            gross_quote=gross_base*f.price_quote
            quote_in=gross_quote-quote_fee
            avg=self.s.average_cost_quote_per_base
            cost_removed=inventory_reduction*avg
            self.s.quote_cash_delta += quote_in
            self.s.base_position -= inventory_reduction
            self.s.realized_pnl_quote += quote_in-cost_removed
            self.s.trading_fees_quote_effect += quote_fee
            if self.s.base_position==0:
                self.s.average_cost_quote_per_base=Decimal("0")

        self._fill_ids.add(f.fill_id)
        return True

    def mark_to_market(self, mark_price_quote: Any) -> dict[str,Decimal]:
        p=D(mark_price_quote)
        if p<=0: raise ValueError("mark price must be positive")
        market_value=self.s.base_position*p
        unrealized=(p-self.s.average_cost_quote_per_base)*self.s.base_position
        current_bot_value=self.s.quote_cash_delta+market_value
        owner_result=current_bot_value+self.s.withdrawals_quote-self.s.deposits_quote
        return {
            "available_accounted_cash":self.s.quote_cash_delta,
            "base_position":self.s.base_position,
            "money_in_market":market_value,
            "current_bot_value":current_bot_value,
            "realized_pnl":self.s.realized_pnl_quote,
            "unrealized_pnl":unrealized,
            "deposited":self.s.deposits_quote,
            "withdrawn":self.s.withdrawals_quote,
            "owner_total_result":owner_result,
        }

def reconcile_balances(*, accounted_quote: Any, accounted_base: Any,
                       exchange_quote_available: Any, exchange_quote_in_order: Any,
                       exchange_base_available: Any, exchange_base_in_order: Any,
                       quote_tolerance: Any="0.01", base_tolerance: Any="0.00000001") -> dict[str,Any]:
    aq=D(accounted_quote); ab=D(accounted_base)
    eq=D(exchange_quote_available)+D(exchange_quote_in_order)
    eb=D(exchange_base_available)+D(exchange_base_in_order)
    qdiff=eq-aq; bdiff=eb-ab
    ok=abs(qdiff)<=D(quote_tolerance) and abs(bdiff)<=D(base_tolerance)
    return {
        "ok":ok,
        "quote_difference":qdiff,
        "base_difference":bdiff,
        "exchange_quote_total":eq,
        "exchange_base_total":eb,
    }
