from decimal import Decimal
from pathlib import Path
import sys
BASE=Path(__file__).parent
sys.path.insert(0,str(BASE))
from treasury import FundingPolicy,TreasuryAction,TreasuryLedger,decide_funding

p=FundingPolicy.make(min_usdc='100',target_usdc='250',max_usdc='400',max_conversion_eur='200',allow_auto_defund=False)

d=decide_funding(policy=p,usdc_available='200',usdc_in_order='25',eur_available='300',usdc_eur='0.998')
assert d.action==TreasuryAction.HOLD

d=decide_funding(policy=p,usdc_available='40',usdc_in_order='10',eur_available='500',usdc_eur='1.0')
assert d.action==TreasuryAction.FUND_USDC
assert d.usdc_amount==Decimal('200')
assert d.estimated_owner_notional_eur==Decimal('200.0')

d=decide_funding(policy=p,usdc_available='0',usdc_in_order='0',eur_available='50',usdc_eur='1.0')
assert d.action==TreasuryAction.FUND_USDC
assert d.usdc_amount==Decimal('50')

d=decide_funding(policy=p,usdc_available='80',usdc_in_order='0',pending_funding_usdc='30',eur_available='500',usdc_eur='1')
assert d.action==TreasuryAction.HOLD

d=decide_funding(policy=p,usdc_available='450',usdc_in_order='0',eur_available='100',usdc_eur='1')
assert d.action==TreasuryAction.HOLD

p_defund=FundingPolicy.make(min_usdc='100',target_usdc='250',max_usdc='400',max_conversion_eur='100',allow_auto_defund=True)
d=decide_funding(policy=p_defund,usdc_available='500',usdc_in_order='0',eur_available='0',usdc_eur='1')
assert d.action==TreasuryAction.DEFUND_USDC
assert d.usdc_amount==Decimal('100')

try:
    decide_funding(policy=p,usdc_available='0',usdc_in_order='0',eur_available='500',usdc_eur='1',invoked_from_trade_cycle=True)
    raise AssertionError('per-trade treasury conversion accepted')
except ValueError:
    pass

try:
    FundingPolicy.make(min_usdc='100',target_usdc='250',max_usdc='400',max_conversion_eur='200',per_trade_conversion_allowed=True)
    raise AssertionError('per-trade funding policy accepted')
except ValueError:
    pass

t=TreasuryLedger(eur_balance=Decimal('500'),usdc_balance=Decimal('0'))
before=t.owner_value_eur(usdc_eur='1')
t.fund_usdc(usdc_received='200',eur_spent='199.50',fee_eur='0.20')
after=t.owner_value_eur(usdc_eur='1')
assert before==Decimal('500')
assert after==Decimal('500.30')
assert t.cumulative_conversion_fees_eur==Decimal('0.20')

t.defund_usdc(usdc_spent='50',eur_received='49.80',fee_eur='0.05')
assert t.usdc_balance==Decimal('150')
assert t.cumulative_conversion_fees_eur==Decimal('0.25')

print('Treasury USDC funding contract PASS')
