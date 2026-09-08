"""Tests for StateReconciler, Manual Trade Isolation, and Crash Recovery."""

import pytest
from src.core.models.trade import StrategyTrade, StrategyLeg, StrategyState, LegStatus
from src.core.models.instrument import OptionType
from src.core.models.position import Position
from src.reconciliation.reconciler import StateReconciler


@pytest.mark.asyncio
async def test_reconcile_isolates_unrelated_manual_trades(mock_exchange):
    """
    CRITICAL TEST: Unrelated manual trades on the account must be isolated
    and must NOT halt the bot.
    """
    reconciler = StateReconciler(exchange_adapter=mock_exchange)

    # Setup unrelated manual positions on the exchange (e.g. BTC Perp, ETH Option)
    mock_exchange.positions = [
        Position(instrument_id="999", symbol="BTCUSD_PERP", size=1.5, entry_price=94000.0),
        Position(instrument_id="888", symbol="C-ETH-3500-010926", size=10.0, entry_price=120.0),
    ]

    trade = StrategyTrade(
        strategy_trade_id="STRANGLE_20260901_090000",
        strategy_name="btc_short_strangle",
        trade_date="2026-09-01",
        state=StrategyState.IDLE,
    )

    res = await reconciler.reconcile(trade)
    # Must remain synchronized and NOT halt
    assert res.is_synchronized is True
    assert res.status == "CLEAN_IDLE"
    assert res.details["manual_positions_count"] == 2


@pytest.mark.asyncio
async def test_reconcile_handles_manual_close_of_strategy_leg(mock_exchange):
    """
    If a user manually closes one strategy leg on Delta, reconciler updates
    that leg to MANUALLY_CLOSED and keeps the other leg running.
    """
    reconciler = StateReconciler(exchange_adapter=mock_exchange)

    ce_leg = StrategyLeg(
        leg_id="CE_1",
        option_type=OptionType.CALL,
        instrument_id="101",
        symbol="C-BTC-98000-010926",
        strike=98000.0,
        expiry_date="010926",
        quantity=1.0,
        intended_premium=100.0,
        entry_fill_price=100.0,
        status=LegStatus.OPEN,
    )
    pe_leg = StrategyLeg(
        leg_id="PE_1",
        option_type=OptionType.PUT,
        instrument_id="201",
        symbol="P-BTC-92000-010926",
        strike=92000.0,
        expiry_date="010926",
        quantity=1.0,
        intended_premium=100.0,
        entry_fill_price=100.0,
        status=LegStatus.OPEN,
    )

    trade = StrategyTrade(
        strategy_trade_id="STRANGLE_20260901_090000",
        strategy_name="btc_short_strangle",
        trade_date="2026-09-01",
        ce_leg=ce_leg,
        pe_leg=pe_leg,
        state=StrategyState.ACTIVE,
    )

    # Simulate exchange state: CE leg was manually closed (size = 0), PE is still open (-1.0)
    mock_exchange.positions = [
        Position(instrument_id="201", symbol="P-BTC-92000-010926", size=-1.0, entry_price=100.0),
    ]
    # Inject actual fill data for the CE leg (product_id=101), simulating a manual BUY at $5
    mock_exchange.fills_by_instrument = {
        "101": [
            {
                "side": "buy",
                "fill_price": "5.0",
                "size": "1",
                "commission": "0.0025",
                "created_at": "2026-09-01T10:00:00Z",
            }
        ]
    }

    res = await reconciler.reconcile(trade)

    assert res.is_synchronized is True
    assert trade.ce_leg.status == LegStatus.MANUALLY_CLOSED
    assert trade.ce_leg.exit_price == 5.0                          # Actual fill price captured
    assert trade.ce_leg.fees == pytest.approx(0.0025, abs=1e-6)    # Actual fees captured
    # P&L: (entry=100 - exit=5) × qty=1 × contract=0.001 = 0.095
    assert trade.ce_leg.realized_pnl == pytest.approx(0.095, abs=1e-5)
    assert trade.pe_leg.status == LegStatus.OPEN                   # PE unaffected
    assert trade.state == StrategyState.ACTIVE


@pytest.mark.asyncio
async def test_reconcile_captures_delta_price_field_and_entry_plus_exit_fees(mock_exchange):
    """Live Delta fills use `price` (not fill_price) and UTC timestamps vs IST entry."""
    reconciler = StateReconciler(exchange_adapter=mock_exchange)

    pe_leg = StrategyLeg(
        leg_id="PE_1",
        option_type=OptionType.PUT,
        instrument_id="150988",
        symbol="P-BTC-79800-060926",
        strike=79800.0,
        expiry_date="060926",
        quantity=5.0,
        intended_premium=89.0,
        entry_fill_price=89.0,
        entry_timestamp="2026-09-06T09:08:46.941105+05:30",
        status=LegStatus.OPEN,
    )
    trade = StrategyTrade(
        strategy_trade_id="STRANGLE_20260906_090842",
        strategy_name="short_strangle",
        trade_date="2026-09-06",
        pe_leg=pe_leg,
        state=StrategyState.ACTIVE,
    )
    mock_exchange.positions = []
    mock_exchange.fills_by_instrument = {
        "150988": [
            {
                "side": "sell",
                "price": "89",
                "size": "5",
                "commission": "0.0183785",
                "created_at": "2026-09-06T03:38:46.710152Z",
            },
            {
                "side": "buy",
                "price": "194",
                "size": "5",
                "commission": "0.040061",
                "created_at": "2026-09-06T06:48:38.917195Z",
            },
        ]
    }

    res = await reconciler.reconcile(trade)
    assert res.is_synchronized is True
    assert trade.pe_leg.status == LegStatus.MANUALLY_CLOSED
    assert trade.pe_leg.exit_price == 194.0
    assert trade.pe_leg.realized_pnl == pytest.approx(-0.525, abs=1e-5)
    assert trade.pe_leg.fees == pytest.approx(0.0584395, abs=1e-6)
    assert trade.state == StrategyState.COMPLETED


@pytest.mark.asyncio
async def test_reconcile_handles_partial_size_change_without_halt(mock_exchange):
    """
    CRITICAL TEST: If a leg quantity changes partially (e.g. 500 contracts reduced to 50 due to partial fill/close),
    the reconciler updates leg quantity smoothly and does NOT crash or trigger SAFE_HALT.
    """
    reconciler = StateReconciler(exchange_adapter=mock_exchange)

    ce_leg = StrategyLeg(
        leg_id="CE_1",
        option_type=OptionType.CALL,
        instrument_id="101",
        symbol="C-BTC-98000-010926",
        strike=98000.0,
        expiry_date="010926",
        quantity=500.0,
        status=LegStatus.OPEN,
        intended_premium=100.0,
        entry_fill_price=100.0,
        sl_price=200.0,
        exchange_sl_active=True,
    )

    trade = StrategyTrade(
        strategy_trade_id="STRANGLE_20260901_090000",
        strategy_name="btc_short_strangle",
        trade_date="2026-09-01",
        ce_leg=ce_leg,
        state=StrategyState.ACTIVE,
    )

    # Position on exchange reduced to -50.0 (partial close/fill)
    mock_exchange.positions = [
        Position(instrument_id="101", symbol="C-BTC-98000-010926", size=-50.0, entry_price=100.0),
    ]

    res = await reconciler.reconcile(trade)
    assert res.is_synchronized is True
    assert trade.state == StrategyState.ACTIVE
    assert trade.ce_leg.quantity == 50.0
    assert "C-BTC-98000-010926" in res.details["updated_legs"]


@pytest.mark.asyncio
async def test_reconcile_unexpected_long_position_triggers_safe_halt(mock_exchange):
    """
    If an unexpected LONG direction position occurs on a short strategy symbol, reconciler signals SAFE_HALT.
    """
    reconciler = StateReconciler(exchange_adapter=mock_exchange)

    ce_leg = StrategyLeg(
        leg_id="CE_1",
        option_type=OptionType.CALL,
        instrument_id="101",
        symbol="C-BTC-98000-010926",
        strike=98000.0,
        expiry_date="010926",
        quantity=1.0,
        status=LegStatus.OPEN,
        intended_premium=100.0,
    )

    trade = StrategyTrade(
        strategy_trade_id="STRANGLE_20260901_090000",
        strategy_name="btc_short_strangle",
        trade_date="2026-09-01",
        ce_leg=ce_leg,
        state=StrategyState.ACTIVE,
    )

    # Unexpected LONG position (+1.0) on exchange for a short strangle leg
    mock_exchange.positions = [
        Position(instrument_id="101", symbol="C-BTC-98000-010926", size=1.0, entry_price=100.0),
    ]

    res = await reconciler.reconcile(trade)
    assert res.is_synchronized is False
    assert res.status == "SAFE_HALT"
    assert trade.state == StrategyState.SAFE_HALT


@pytest.mark.asyncio
async def test_engine_startup_reconciliation_failure_blocks_strategy(test_settings, mock_exchange):
    """
    If exchange reconciliation fails on startup (e.g. 401 unwhitelisted IP, network error),
    the strategy must NOT become ACTIVE, and trading must remain blocked.
    """
    from src.engine import TradingEngine

    # Make exchange throw an API error on get_positions
    mock_exchange.fail_specific_symbol = "FAIL_ALL"

    engine = TradingEngine(settings=test_settings)
    engine.delta_adapter = mock_exchange
    engine.exchange_service.register_adapter(mock_exchange)
    engine.reconciler = StateReconciler(exchange_adapter=mock_exchange)
    engine.execution_engine.exchange = mock_exchange

    await engine.start()

    status = engine.get_status()
    # Strategy MUST NOT be active
    assert status["strategy_active"] is False
    assert status["trading_enabled"] is False
    assert status["reconciliation"]["status"] == "EXCHANGE_QUERY_FAILED"
    assert status["reconciliation"]["is_synchronized"] is False

    await engine.stop()


@pytest.mark.asyncio
async def test_reconcile_crash_before_bracket_creation_reattaches_bracket(mock_exchange):
    """
    Test scenario: Crash after entry fill but before bracket creation.
    Reconciler verifies position, validates entry & SL price, and safely attaches the missing native bracket.
    """
    reconciler = StateReconciler(exchange_adapter=mock_exchange)

    ce_leg = StrategyLeg(
        leg_id="CE_1",
        option_type=OptionType.CALL,
        instrument_id="101",
        symbol="C-BTC-98000-010926",
        strike=98000.0,
        expiry_date="010926",
        quantity=1.0,
        intended_premium=100.0,
        entry_fill_price=100.0,
        sl_price=200.0,
        status=LegStatus.OPEN,
        exchange_sl_active=False,
    )
    pe_leg = StrategyLeg(
        leg_id="PE_1",
        option_type=OptionType.PUT,
        instrument_id="201",
        symbol="P-BTC-92000-010926",
        strike=92000.0,
        expiry_date="010926",
        quantity=1.0,
        intended_premium=100.0,
        entry_fill_price=100.0,
        sl_price=200.0,
        status=LegStatus.OPEN,
        exchange_sl_active=False,
    )

    trade = StrategyTrade(
        strategy_trade_id="STRANGLE_20260901_090000",
        strategy_name="btc_short_strangle",
        trade_date="2026-09-01",
        ce_leg=ce_leg,
        pe_leg=pe_leg,
        state=StrategyState.ACTIVE,
    )

    # Positions exist on exchange (-1.0 each), but zero orders/brackets exist yet
    mock_exchange.positions = [
        Position(instrument_id="101", symbol="C-BTC-98000-010926", size=-1.0, entry_price=100.0),
        Position(instrument_id="201", symbol="P-BTC-92000-010926", size=-1.0, entry_price=100.0),
    ]
    mock_exchange.orders = {}

    res = await reconciler.reconcile(trade)
    assert res.is_synchronized is True
    assert trade.ce_leg.exchange_sl_active is True
    assert trade.ce_leg.bracket_order_id == "BRK_101_200"
    assert trade.pe_leg.exchange_sl_active is True
    assert trade.pe_leg.bracket_order_id == "BRK_201_200"


@pytest.mark.asyncio
async def test_reconcile_crash_after_bracket_creation_discovers_existing_bracket(mock_exchange):
    """
    Test scenario: Crash after bracket creation.
    Reconciler finds existing active bracket on exchange, restores ID, and creates NO duplicate orders.
    """
    reconciler = StateReconciler(exchange_adapter=mock_exchange)

    ce_leg = StrategyLeg(
        leg_id="CE_1",
        option_type=OptionType.CALL,
        instrument_id="101",
        symbol="C-BTC-98000-010926",
        strike=98000.0,
        expiry_date="010926",
        quantity=1.0,
        intended_premium=100.0,
        entry_fill_price=100.0,
        sl_price=200.0,
        status=LegStatus.OPEN,
    )
    pe_leg = StrategyLeg(
        leg_id="PE_1",
        option_type=OptionType.PUT,
        instrument_id="201",
        symbol="P-BTC-92000-010926",
        strike=92000.0,
        expiry_date="010926",
        quantity=1.0,
        intended_premium=100.0,
        entry_fill_price=100.0,
        sl_price=200.0,
        status=LegStatus.OPEN,
    )

    trade = StrategyTrade(
        strategy_trade_id="STRANGLE_20260901_090000",
        strategy_name="btc_short_strangle",
        trade_date="2026-09-01",
        ce_leg=ce_leg,
        pe_leg=pe_leg,
        state=StrategyState.ACTIVE,
    )

    mock_exchange.positions = [
        Position(instrument_id="101", symbol="C-BTC-98000-010926", size=-1.0, entry_price=100.0),
        Position(instrument_id="201", symbol="P-BTC-92000-010926", size=-1.0, entry_price=100.0),
    ]
    # Pre-create brackets on exchange
    await mock_exchange.create_bracket_order(instrument_id="101", stop_loss_price=200.0)
    await mock_exchange.create_bracket_order(instrument_id="201", stop_loss_price=200.0)
    initial_order_count = len(mock_exchange.orders)

    res = await reconciler.reconcile(trade)
    assert res.is_synchronized is True
    assert trade.ce_leg.exchange_sl_active is True
    assert trade.pe_leg.exchange_sl_active is True
    # Verify no duplicate orders were created
    assert len(mock_exchange.orders) == initial_order_count


@pytest.mark.asyncio
async def test_reconcile_corrupt_ambiguous_state_triggers_safe_halt(mock_exchange):
    """
    Test scenario: Missing bracket on exchange and persisted state is corrupt/missing entry fill price.
    Reconciler MUST NOT guess the SL price and must enter SAFE_HALT.
    """
    reconciler = StateReconciler(exchange_adapter=mock_exchange)

    ce_leg = StrategyLeg(
        leg_id="CE_1",
        option_type=OptionType.CALL,
        instrument_id="101",
        symbol="C-BTC-98000-010926",
        strike=98000.0,
        expiry_date="010926",
        quantity=1.0,
        intended_premium=100.0,
        entry_fill_price=0.0,  # Corrupt / Missing
        sl_price=None,         # Corrupt / Missing
        status=LegStatus.OPEN,
    )

    trade = StrategyTrade(
        strategy_trade_id="STRANGLE_20260901_090000",
        strategy_name="btc_short_strangle",
        trade_date="2026-09-01",
        ce_leg=ce_leg,
        state=StrategyState.ACTIVE,
    )

    mock_exchange.positions = [
        Position(instrument_id="101", symbol="C-BTC-98000-010926", size=-1.0, entry_price=100.0),
    ]
    mock_exchange.orders = {}

    res = await reconciler.reconcile(trade)
    assert res.is_synchronized is False
    assert res.status == "SAFE_HALT"
    assert trade.state == StrategyState.SAFE_HALT
