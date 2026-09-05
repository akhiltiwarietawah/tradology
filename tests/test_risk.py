"""Tests for RiskManager, Max Daily Loss, and Kill Switch."""

import pytest
from src.risk.risk_manager import RiskManager
from src.core.models.trade import StrategyTrade, StrategyState


def test_kill_switch_blocks_trading():
    rm = RiskManager(max_daily_loss_usd=500.0, kill_switch=False)
    safe, msg = rm.check_pre_trade_safety()
    assert safe is True

    # Activate kill switch
    rm.activate_kill_switch()
    assert rm.is_kill_switch_active is True
    safe, msg = rm.check_pre_trade_safety()
    assert safe is False
    assert "Kill switch" in msg


def test_max_daily_loss_breach():
    rm = RiskManager(max_daily_loss_pct=None, max_daily_loss_usd=500.0)
    trade = StrategyTrade(
        strategy_trade_id="STR_TEST",
        strategy_name="btc_short_strangle",
        trade_date="2026-09-01",
        total_realized_pnl=-300.0,
        total_unrealized_pnl=-250.0,  # Total = -$550
        state=StrategyState.ACTIVE,
    )

    breached, total = rm.check_daily_loss_limit(trade)
    assert breached is True
    assert total == -550.0

    safe, msg = rm.check_pre_trade_safety(trade)
    assert safe is False
    assert "Max daily loss breached" in msg


def test_dynamic_max_daily_loss_scales_with_quantity():
    from src.core.models.trade import StrategyLeg
    from src.core.models.instrument import OptionType

    rm = RiskManager(max_daily_loss_pct=2.1, max_daily_loss_usd=500.0)

    # 1. Test with 1 contract (0.001 BTC): Total Entry Premium = ($100 + $100) * 1 * 0.001 = $0.20 USD
    ce_leg_1 = StrategyLeg(
        leg_id="L1",
        option_type=OptionType.CALL,
        instrument_id="1",
        symbol="C-BTC-100k",
        strike=100000,
        expiry_date="2026-09-01",
        quantity=1.0,
        intended_premium=100.0,
        entry_fill_price=100.0,
        contract_value=0.001,
    )
    pe_leg_1 = StrategyLeg(
        leg_id="L2",
        option_type=OptionType.PUT,
        instrument_id="2",
        symbol="P-BTC-90k",
        strike=90000,
        expiry_date="2026-09-01",
        quantity=1.0,
        intended_premium=100.0,
        entry_fill_price=100.0,
        contract_value=0.001,
    )
    trade_small = StrategyTrade(
        strategy_trade_id="STR_SMALL",
        strategy_name="btc_short_strangle",
        trade_date="2026-09-01",
        ce_leg=ce_leg_1,
        pe_leg=pe_leg_1,
        total_realized_pnl=0.0,
        total_unrealized_pnl=-0.30,  # Loss of $0.30
        state=StrategyState.ACTIVE,
    )

    # Total entry premium = $0.20, 210% (2.1x) limit = $0.42
    assert trade_small.total_entry_premium == 0.20
    assert rm.get_effective_max_loss_usd(trade_small) == 0.42

    # -$0.30 is within $0.42 limit
    breached, _ = rm.check_daily_loss_limit(trade_small)
    assert breached is False

    # Loss drops to -$0.45 -> Breached!
    trade_small.total_unrealized_pnl = -0.45
    breached, _ = rm.check_daily_loss_limit(trade_small)
    assert breached is True

    # 2. Test with 1000 contracts (1.0 BTC): Total Entry Premium = ($100 + $100) * 1000 * 0.001 = $200.00 USD
    ce_leg_large = StrategyLeg(
        leg_id="L1",
        option_type=OptionType.CALL,
        instrument_id="1",
        symbol="C-BTC-100k",
        strike=100000,
        expiry_date="2026-09-01",
        quantity=1000.0,
        intended_premium=100.0,
        entry_fill_price=100.0,
        contract_value=0.001,
    )
    pe_leg_large = StrategyLeg(
        leg_id="L2",
        option_type=OptionType.PUT,
        instrument_id="2",
        symbol="P-BTC-90k",
        strike=90000,
        expiry_date="2026-09-01",
        quantity=1000.0,
        intended_premium=100.0,
        entry_fill_price=100.0,
        contract_value=0.001,
    )
    trade_large = StrategyTrade(
        strategy_trade_id="STR_LARGE",
        strategy_name="btc_short_strangle",
        trade_date="2026-09-01",
        ce_leg=ce_leg_large,
        pe_leg=pe_leg_large,
        total_realized_pnl=0.0,
        total_unrealized_pnl=-350.0,  # Loss of $350
        state=StrategyState.ACTIVE,
    )

    # Total entry premium = $200.00, 210% (2.1x) limit = $420.00
    assert trade_large.total_entry_premium == 200.00
    assert rm.get_effective_max_loss_usd(trade_large) == 420.00

    # -$350 is within $420 limit
    breached, _ = rm.check_daily_loss_limit(trade_large)
    assert breached is False

    # Loss drops to -$430 -> Breached!
    trade_large.total_unrealized_pnl = -430.0
    breached, _ = rm.check_daily_loss_limit(trade_large)
    assert breached is True


def test_settings_single_source_of_truth_for_risk_manager():
    from src.config.settings import Settings
    from src.core.models.trade import StrategyLeg
    from src.core.models.instrument import OptionType

    # Settings loads runtime configuration (e.g. 2.1 from default or .env)
    settings = Settings(max_daily_loss_pct=2.1, max_daily_loss_usd=500.0)
    assert settings.max_daily_loss_pct == 2.1

    # RiskManager is instantiated directly with Settings values
    rm = RiskManager(
        max_daily_loss_pct=settings.max_daily_loss_pct,
        max_daily_loss_usd=settings.max_daily_loss_usd,
    )

    trade = StrategyTrade(
        strategy_trade_id="STR_TEST",
        strategy_name="btc_short_strangle",
        trade_date="2026-09-01",
        ce_leg=StrategyLeg(
            leg_id="L1",
            option_type=OptionType.CALL,
            instrument_id="1",
            symbol="C-BTC",
            strike=100000,
            expiry_date="2026-09-01",
            quantity=10.0,
            intended_premium=100.0,
            entry_fill_price=100.0,
            contract_value=0.001,
        ),
        pe_leg=StrategyLeg(
            leg_id="L2",
            option_type=OptionType.PUT,
            instrument_id="2",
            symbol="P-BTC",
            strike=90000,
            expiry_date="2026-09-01",
            quantity=10.0,
            intended_premium=100.0,
            entry_fill_price=100.0,
            contract_value=0.001,
        ),
        state=StrategyState.ACTIVE,
    )

    # 10 contracts * ($100 + $100) * 0.001 = $2.00 entry premium
    assert trade.total_entry_premium == 2.00
    # $2.00 * 2.1 = $4.20 limit
    assert rm.get_effective_max_loss_usd(trade) == 4.20


