import pytest
from datetime import datetime, timezone
from src.strategies.short_strangle.selector import OptionSelector, OptionSelectionError


def test_select_strangle_legs_success(mock_exchange):
    selector = OptionSelector()
    today = datetime.now(timezone.utc).date()
    import asyncio
    chain = asyncio.run(mock_exchange.get_option_chain("BTC", today))
    tickers_map = asyncio.run(mock_exchange.get_tickers())

    ce_inst, ce_tick, pe_inst, pe_tick = selector.select_strangle_legs(
        option_chain=chain,
        tickers_map=tickers_map,
        spot_price=95000.0,
        target_premium=100.0,
        tolerance_usd=30.0,
    )

    # Validate Call Leg: Strike must be > spot (95000), closest to $100
    assert ce_inst.is_call
    assert ce_inst.strike_price > 95000.0
    assert ce_inst.strike_price == 98000.0  # $98.50 premium is closest to $100
    assert abs(ce_tick.mid_price - 100.0) <= 30.0

    # Validate Put Leg: Strike must be < spot (95000), closest to $100
    assert pe_inst.is_put
    assert pe_inst.strike_price < 95000.0
    assert pe_inst.strike_price == 92000.0  # $102.00 premium is closest to $100
    assert abs(pe_tick.mid_price - 100.0) <= 30.0


def test_select_strangle_legs_tolerance_rejection(mock_exchange):
    selector = OptionSelector()
    today = datetime.now(timezone.utc).date()
    import asyncio
    chain = asyncio.run(mock_exchange.get_option_chain("BTC", today))
    tickers_map = asyncio.run(mock_exchange.get_tickers())

    # Set narrow tolerance (e.g. $1.00) where $98.50 ($1.50 off) and $102.00 ($2.00 off) will fail
    with pytest.raises(OptionSelectionError, match="No OTM Call found"):
        selector.select_strangle_legs(
            option_chain=chain,
            tickers_map=tickers_map,
            spot_price=95000.0,
            target_premium=100.0,
            tolerance_usd=1.0,
        )


def test_select_strangle_legs_otm_enforcement(mock_exchange):
    selector = OptionSelector()
    today = datetime.now(timezone.utc).date()
    import asyncio
    chain = asyncio.run(mock_exchange.get_option_chain("BTC", today))
    tickers_map = asyncio.run(mock_exchange.get_tickers())

    # If spot price is 100,000, our Call strikes (96k, 98k) are ITM -> must be rejected
    with pytest.raises(OptionSelectionError, match="No OTM Call found"):
        selector.select_strangle_legs(
            option_chain=chain,
            tickers_map=tickers_map,
            spot_price=100000.0,
            target_premium=100.0,
            tolerance_usd=50.0,
        )
