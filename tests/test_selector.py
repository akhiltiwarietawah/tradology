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
    assert 70.0 <= ce_tick.sell_premium <= 130.0
    assert 70.0 <= pe_tick.sell_premium <= 130.0


def test_select_strangle_legs_uses_bid_not_mark():
    """Mark in band + bid below band must be skipped (today's $80.50 mark / $64 fill)."""
    from src.core.models.instrument import Instrument, OptionChain, InstrumentType, OptionType
    from src.core.models.market_data import Ticker

    selector = OptionSelector()
    ce = Instrument(
        exchange="mock",
        instrument_id="1",
        symbol="C-BTC-80000-080926",
        underlying="BTC",
        instrument_type=InstrumentType.OPTION,
        option_type=OptionType.CALL,
        strike_price=80000.0,
        contract_value=0.001,
    )
    pe_cheap = Instrument(
        exchange="mock",
        instrument_id="2",
        symbol="P-BTC-78200-080926",
        underlying="BTC",
        instrument_type=InstrumentType.OPTION,
        option_type=OptionType.PUT,
        strike_price=78200.0,
        contract_value=0.001,
    )
    pe_ok = Instrument(
        exchange="mock",
        instrument_id="3",
        symbol="P-BTC-78600-080926",
        underlying="BTC",
        instrument_type=InstrumentType.OPTION,
        option_type=OptionType.PUT,
        strike_price=78600.0,
        contract_value=0.001,
    )
    chain = OptionChain(
        exchange="mock",
        underlying="BTC",
        expiry_date=datetime.now(timezone.utc).date(),
        calls=[ce],
        puts=[pe_cheap, pe_ok],
    )
    tickers = {
        ce.symbol: Ticker(symbol=ce.symbol, instrument_id="1", mark_price=102.0, best_bid=101.0, best_ask=103.0),
        pe_cheap.symbol: Ticker(
            symbol=pe_cheap.symbol, instrument_id="2", mark_price=80.50, best_bid=64.0, best_ask=97.0
        ),
        pe_ok.symbol: Ticker(
            symbol=pe_ok.symbol, instrument_id="3", mark_price=96.0, best_bid=94.0, best_ask=98.0
        ),
    }

    _, _, pe_inst, pe_tick = selector.select_strangle_legs(
        option_chain=chain,
        tickers_map=tickers,
        spot_price=79200.0,
        target_premium=100.0,
        tolerance_usd=30.0,
    )
    assert pe_inst.symbol == pe_ok.symbol
    assert pe_tick.sell_premium == 94.0


def test_select_strangle_legs_rejects_mark_only_quotes():
    from src.core.models.instrument import Instrument, OptionChain, InstrumentType, OptionType
    from src.core.models.market_data import Ticker

    selector = OptionSelector()
    ce = Instrument(
        exchange="mock",
        instrument_id="1",
        symbol="C-BTC-80000-080926",
        underlying="BTC",
        instrument_type=InstrumentType.OPTION,
        option_type=OptionType.CALL,
        strike_price=80000.0,
        contract_value=0.001,
    )
    pe = Instrument(
        exchange="mock",
        instrument_id="2",
        symbol="P-BTC-78200-080926",
        underlying="BTC",
        instrument_type=InstrumentType.OPTION,
        option_type=OptionType.PUT,
        strike_price=78200.0,
        contract_value=0.001,
    )
    chain = OptionChain(
        exchange="mock",
        underlying="BTC",
        expiry_date=datetime.now(timezone.utc).date(),
        calls=[ce],
        puts=[pe],
    )
    tickers = {
        ce.symbol: Ticker(symbol=ce.symbol, instrument_id="1", mark_price=100.0),
        pe.symbol: Ticker(symbol=pe.symbol, instrument_id="2", mark_price=80.50),
    }
    with pytest.raises(OptionSelectionError, match="sellable bid"):
        selector.select_strangle_legs(
            option_chain=chain,
            tickers_map=tickers,
            spot_price=79200.0,
            target_premium=100.0,
            tolerance_usd=30.0,
        )


def test_select_strangle_legs_tolerance_rejection(mock_exchange):
    selector = OptionSelector()
    today = datetime.now(timezone.utc).date()
    import asyncio
    chain = asyncio.run(mock_exchange.get_option_chain("BTC", today))
    tickers_map = asyncio.run(mock_exchange.get_tickers())

    # Set narrow tolerance (e.g. $1.00) where $98.50 ($1.50 off) and $102.00 ($2.00 off) will fail
    with pytest.raises(OptionSelectionError, match="No OTM Call"):
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
    with pytest.raises(OptionSelectionError, match="No OTM Call"):
        selector.select_strangle_legs(
            option_chain=chain,
            tickers_map=tickers_map,
            spot_price=100000.0,
            target_premium=100.0,
            tolerance_usd=50.0,
        )
