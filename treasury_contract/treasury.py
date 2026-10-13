#!/usr/bin/env python3
"""Strategy-independent treasury contract for BTC/USDC execution with EUR owner reporting.

Reference/test module only. It does not perform network I/O or place orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any


def D(x: Any) -> Decimal:
    try:
        return Decimal(str(x))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"not a decimal: {x!r}")


class TreasuryAction(str, Enum):
    HOLD="HOLD"
    FUND_USDC="FUND_USDC"
    DEFUND_USDC="DEFUND_USDC"


@dataclass(frozen=True)
class FundingPolicy:
    min_usdc: Decimal
    target_usdc: Decimal
    max_usdc: Decimal
    max_conversion_eur: Decimal
    allow_auto_defund: bool=False
    per_trade_conversion_allowed: bool=False

    @classmethod
    def make(cls, *, min_usdc: Any, target_usdc: Any, max_usdc: Any,
             max_conversion_eur: Any, allow_auto_defund: bool=False,
             per_trade_conversion_allowed: bool=False):
        p=cls(
            min_usdc=D(min_usdc),
            target_usdc=D(target_usdc),
            max_usdc=D(max_usdc),
            max_conversion_eur=D(max_conversion_eur),
            allow_auto_defund=bool(allow_auto_defund),
            per_trade_conversion_allowed=bool(per_trade_conversion_allowed),
        )
        p.validate()
        return p

    def validate(self) -> None:
        if self.min_usdc < 0:
            raise ValueError("min_usdc cannot be negative")
        if not (self.min_usdc <= self.target_usdc <= self.max_usdc):
            raise ValueError("require min_usdc <= target_usdc <= max_usdc")
        if self.max_usdc <= 0:
            raise ValueError("max_usdc must be positive")
        if self.max_conversion_eur <= 0:
            raise ValueError("max_conversion_eur must be positive")
        if self.per_trade_conversion_allowed:
            raise ValueError("per-trade EUR<->USDC conversion is forbidden by the F0 execution decision")


@dataclass(frozen=True)
class TreasuryDecision:
    action: TreasuryAction
    usdc_amount: Decimal
    estimated_owner_notional_eur: Decimal
    reason: str


def decide_funding(*, policy: FundingPolicy, usdc_available: Any,
                   usdc_in_order: Any, eur_available: Any,
                   usdc_eur: Any, pending_funding_usdc: Any="0",
                   invoked_from_trade_cycle: bool=False) -> TreasuryDecision:
    policy.validate()
    if invoked_from_trade_cycle:
        raise ValueError("treasury conversion cannot be invoked from a strategy trade cycle")

    ua=D(usdc_available); uo=D(usdc_in_order); ea=D(eur_available)
    pending=D(pending_funding_usdc); fx=D(usdc_eur)
    for name,v in (("usdc_available",ua),("usdc_in_order",uo),("eur_available",ea),("pending_funding_usdc",pending)):
        if v < 0:
            raise ValueError(f"{name} cannot be negative")
    if fx <= 0:
        raise ValueError("USDC/EUR valuation must be positive")

    working=ua+uo+pending

    if working < policy.min_usdc:
        desired=policy.target_usdc-working
        max_by_owner=policy.max_conversion_eur/fx
        max_by_cash=ea/fx
        amount=min(desired,max_by_owner,max_by_cash)
        if amount <= 0:
            return TreasuryDecision(TreasuryAction.HOLD,Decimal("0"),Decimal("0"),"USDC below minimum but no EUR funding capacity")
        return TreasuryDecision(TreasuryAction.FUND_USDC,amount,amount*fx,"USDC working inventory below configured minimum")

    if working > policy.max_usdc:
        if not policy.allow_auto_defund:
            return TreasuryDecision(TreasuryAction.HOLD,Decimal("0"),Decimal("0"),"USDC above maximum; automatic defunding disabled")
        desired=working-policy.target_usdc
        max_by_owner=policy.max_conversion_eur/fx
        amount=min(desired,max_by_owner,ua)
        if amount <= 0:
            return TreasuryDecision(TreasuryAction.HOLD,Decimal("0"),Decimal("0"),"USDC above maximum but no available inventory can be defunded")
        return TreasuryDecision(TreasuryAction.DEFUND_USDC,amount,amount*fx,"USDC working inventory above configured maximum")

    return TreasuryDecision(TreasuryAction.HOLD,Decimal("0"),Decimal("0"),"USDC working inventory within configured band")


@dataclass
class TreasuryLedger:
    """Owner-currency treasury ledger kept separate from BTC trading P/L."""
    eur_balance: Decimal=Decimal("0")
    usdc_balance: Decimal=Decimal("0")
    cumulative_conversion_fees_eur: Decimal=Decimal("0")
    cumulative_eur_to_usdc: Decimal=Decimal("0")
    cumulative_usdc_to_eur: Decimal=Decimal("0")

    def __post_init__(self):
        self.eur_balance=D(self.eur_balance)
        self.usdc_balance=D(self.usdc_balance)
        if self.eur_balance < 0 or self.usdc_balance < 0:
            raise ValueError("initial treasury balances cannot be negative")

    def fund_usdc(self, *, usdc_received: Any, eur_spent: Any, fee_eur: Any="0") -> None:
        u=D(usdc_received); e=D(eur_spent); fee=D(fee_eur)
        if u<=0 or e<=0 or fee<0:
            raise ValueError("invalid EUR->USDC conversion")
        total=e+fee
        if total>self.eur_balance:
            raise ValueError("insufficient EUR treasury balance")
        self.eur_balance-=total
        self.usdc_balance+=u
        self.cumulative_eur_to_usdc+=e
        self.cumulative_conversion_fees_eur+=fee

    def defund_usdc(self, *, usdc_spent: Any, eur_received: Any, fee_eur: Any="0") -> None:
        u=D(usdc_spent); e=D(eur_received); fee=D(fee_eur)
        if u<=0 or e<=0 or fee<0:
            raise ValueError("invalid USDC->EUR conversion")
        if u>self.usdc_balance:
            raise ValueError("insufficient USDC treasury balance")
        net=e-fee
        if net<0:
            raise ValueError("conversion fee exceeds EUR proceeds")
        self.usdc_balance-=u
        self.eur_balance+=net
        self.cumulative_usdc_to_eur+=e
        self.cumulative_conversion_fees_eur+=fee

    def owner_value_eur(self, *, usdc_eur: Any) -> Decimal:
        fx=D(usdc_eur)
        if fx<=0:
            raise ValueError("USDC/EUR valuation must be positive")
        return self.eur_balance+self.usdc_balance*fx
