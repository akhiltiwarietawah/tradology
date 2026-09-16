"""Tests for user-scoped platform ledger attribution and P&L."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update, text

from src.core.models.instrument import OptionType
from src.core.models.order import Fill, Order, OrderSide, OrderState, OrderType
from src.core.models.trade import LegStatus, StrategyLeg, StrategyState, StrategyTrade
from src.persistence.models import FillModel, OrderModel, TradeModel
from src.persistence.platform_models import AccountPositionModel, ExchangeAccountModel
from src.persistence.trade_repository import TradeRepository
from src.platform.ledger.models import PlatformAttribution
from src.platform.ledger.performance_service import PlatformPerformanceService
from src.platform.ledger.pnl import (
    compute_leg_realized_pnl,
    compute_realized_from_trades,
    compute_strategy_unrealized,
    merge_equity_curves,
)
from src.platform.ledger.repository import PlatformLedgerRepository
from src.platform.repositories.platform_repository import PlatformRepository
from src.platform.repositories.sync_repository import SyncRepository


@pytest.fixture
def vault():
    os.environ["CREDENTIALS_ENCRYPTION_KEY"] = "test-platform-key-32chars-minimum!!"
    from src.platform.security.credentials import CredentialVault

    return CredentialVault("test-platform-key-32chars-minimum!!")


async def _seed_user_platform(vault, db, email_prefix: str = "ledger"):
    repo = PlatformRepository(db, vault)
    user = await repo.upsert_user(email=f"{email_prefix}-{uuid.uuid4().hex[:8]}@example.com")
    strategy = await repo.get_strategy_by_code("short_strangle")
    sub = await repo.create_subscription(user.id, strategy.id)
    account = await repo.create_exchange_account(
        user_id=user.id,
        exchange="delta_india",
        label=f"Acct-{uuid.uuid4().hex[:6]}",
        api_key="key12345678",
        api_secret="secret12345678",
    )
    link = await repo.link_strategy_account(subscription_id=sub.id, exchange_account_id=account.id)
    return user, sub, account, link, strategy


def _attribution(user, sub, account, link, strategy) -> PlatformAttribution:
    return PlatformAttribution(
        user_id=user.id,
        subscription_id=sub.id,
        strategy_account_id=link.id,
        exchange_account_id=account.id,
        strategy_code=strategy.code,
    )


async def _record_attributed_trade(repo: TradeRepository, attribution: PlatformAttribution, trade_id: str, net_pnl: float = 50.0):
    now = datetime.now(timezone.utc).isoformat()
    trade = StrategyTrade(
        strategy_trade_id=trade_id,
        strategy_name=attribution.strategy_code,
        trade_date=datetime.now(timezone.utc).date().isoformat(),
        state=StrategyState.COMPLETED,
        ce_leg=StrategyLeg(
            leg_id=f"{trade_id}_CE",
            option_type=OptionType.CALL,
            instrument_id="101",
            symbol="C-BTC-98000-010926",
            strike=98000.0,
            expiry_date=datetime.now(timezone.utc).date().isoformat(),
            quantity=1.0,
            intended_premium=100.0,
            entry_timestamp=now,
            entry_fill_price=100.0,
            exit_price=50.0,
            exit_timestamp=now,
            fees=1.0,
            realized_pnl=net_pnl / 2,
            status=LegStatus.MANUALLY_CLOSED,
        ),
        pe_leg=StrategyLeg(
            leg_id=f"{trade_id}_PE",
            option_type=OptionType.PUT,
            instrument_id="201",
            symbol="P-BTC-92000-010926",
            strike=92000.0,
            expiry_date=datetime.now(timezone.utc).date().isoformat(),
            quantity=1.0,
            intended_premium=100.0,
            entry_timestamp=now,
            entry_fill_price=100.0,
            exit_price=50.0,
            exit_timestamp=now,
            fees=1.0,
            realized_pnl=net_pnl / 2,
            status=LegStatus.MANUALLY_CLOSED,
        ),
    )
    ce_order = Order(
        order_id=f"ORD_{trade_id}_CE",
        client_order_id=f"cid_{trade_id}_CE",
        instrument_id="101",
        symbol=trade.ce_leg.symbol,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=1.0,
        filled_quantity=1.0,
        average_fill_price=100.0,
        state=OrderState.FILLED,
    )
    pe_order = Order(
        order_id=f"ORD_{trade_id}_PE",
        client_order_id=f"cid_{trade_id}_PE",
        instrument_id="201",
        symbol=trade.pe_leg.symbol,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=1.0,
        filled_quantity=1.0,
        average_fill_price=100.0,
        state=OrderState.FILLED,
    )
    await repo.record_entry(trade, ce_order, pe_order, attribution=attribution)


@pytest.mark.asyncio
async def test_platform_order_and_fill_attribution(clean_db, vault):
    if not clean_db.is_connected:
        pytest.skip("Database not available")
    user, sub, account, link, strategy = await _seed_user_platform(vault, clean_db)
    repo = TradeRepository(clean_db)
    attr = _attribution(user, sub, account, link, strategy)
    await _record_attributed_trade(repo, attr, "ATTR_TRADE_001")

    async with clean_db.get_session() as session:
        orders = list((await session.execute(select(OrderModel))).scalars().all())
        fills = list((await session.execute(select(FillModel))).scalars().all())
    assert len(orders) == 2
    assert all(o.user_id == user.id for o in orders)
    assert all(o.strategy_account_id == link.id for o in orders)
    assert len(fills) == 2
    assert all(f.user_id == user.id for f in fills)
    assert all(f.strategy_account_id == link.id for f in fills)


def test_partial_fill_realized_pnl_and_fees():
    pnl = compute_leg_realized_pnl(
        side="sell",
        entry_qty=Decimal("10"),
        exit_qty=Decimal("4"),
        entry_price=Decimal("100"),
        exit_price=Decimal("80"),
        fees=Decimal("2"),
    )
    assert pnl == Decimal("78")


def test_multi_leg_realized_aggregation():
    trades = [
        {"realized_pnl": 25.0, "net_pnl": 23.0, "total_fees": 2.0, "status": "COMPLETED"},
        {"realized_pnl": -10.0, "net_pnl": -11.0, "total_fees": 1.0, "status": "COMPLETED"},
    ]
    summary = compute_realized_from_trades(trades)
    assert summary["available"] is True
    assert summary["realized_pnl"] == pytest.approx(15.0)
    assert summary["total_fees"] == pytest.approx(3.0)


def test_unrealized_pnl_ambiguous_when_symbol_shared():
    open_legs = [{"symbol": "C-BTC-98000", "side": "sell", "quantity": 1, "entry_price": 100.0}]
    owners = {}
    result = compute_strategy_unrealized(open_legs, {"C-BTC-98000": Decimal("90")}, owners, "sa-1")
    assert result["available"] is False


@pytest.mark.asyncio
async def test_strategy_isolation_same_account(clean_db, vault):
    if not clean_db.is_connected:
        pytest.skip("Database not available")
    platform = PlatformRepository(clean_db, vault)
    user = await platform.upsert_user(email=f"iso-{uuid.uuid4().hex[:8]}@example.com")
    strangle = await platform.get_strategy_by_code("short_strangle")
    renko = await platform.get_strategy_by_code("renko_ichimoku_eth")
    if renko is None:
        renko = await platform.get_strategy_by_code("renko_ichimoku")
    sub_a = await platform.create_subscription(user.id, strangle.id)
    sub_b = await platform.create_subscription(user.id, renko.id)
    account = await platform.create_exchange_account(
        user_id=user.id,
        exchange="delta_india",
        label=f"Shared-{uuid.uuid4().hex[:6]}",
        api_key="key12345678",
        api_secret="secret12345678",
    )
    link_a = await platform.link_strategy_account(subscription_id=sub_a.id, exchange_account_id=account.id)
    link_b = await platform.link_strategy_account(subscription_id=sub_b.id, exchange_account_id=account.id)
    repo = TradeRepository(clean_db)
    await _record_attributed_trade(
        repo,
        PlatformAttribution(user.id, sub_a.id, link_a.id, account.id, strangle.code),
        "ISO_A",
        net_pnl=100.0,
    )
    await _record_attributed_trade(
        repo,
        PlatformAttribution(user.id, sub_b.id, link_b.id, account.id, renko.code),
        "ISO_B",
        net_pnl=-20.0,
    )

    ledger = PlatformLedgerRepository(clean_db)
    trades_a = await ledger.get_trades_for_strategy_accounts(user.id, [link_a.id])
    trades_b = await ledger.get_trades_for_strategy_accounts(user.id, [link_b.id])
    assert len(trades_a) == 1
    assert len(trades_b) == 1
    assert compute_realized_from_trades(trades_a)["realized_pnl"] == pytest.approx(100.0)
    assert compute_realized_from_trades(trades_b)["realized_pnl"] == pytest.approx(-20.0)


@pytest.mark.asyncio
async def test_same_strategy_two_accounts_isolated(clean_db, vault):
    if not clean_db.is_connected:
        pytest.skip("Database not available")
    platform = PlatformRepository(clean_db, vault)
    user = await platform.upsert_user(email=f"dual-{uuid.uuid4().hex[:8]}@example.com")
    strategy = await platform.get_strategy_by_code("short_strangle")
    sub = await platform.create_subscription(user.id, strategy.id)
    acct1 = await platform.create_exchange_account(
        user_id=user.id,
        exchange="delta_india",
        label=f"A1-{uuid.uuid4().hex[:6]}",
        api_key="key12345678",
        api_secret="secret12345678",
    )
    acct2 = await platform.create_exchange_account(
        user_id=user.id,
        exchange="delta_india",
        label=f"A2-{uuid.uuid4().hex[:6]}",
        api_key="key12345678",
        api_secret="secret12345678",
    )
    link1 = await platform.link_strategy_account(subscription_id=sub.id, exchange_account_id=acct1.id)
    link2 = await platform.link_strategy_account(subscription_id=sub.id, exchange_account_id=acct2.id)
    repo = TradeRepository(clean_db)
    await _record_attributed_trade(
        repo,
        PlatformAttribution(user.id, sub.id, link1.id, acct1.id, strategy.code),
        "DUAL_1",
        net_pnl=30.0,
    )
    await _record_attributed_trade(
        repo,
        PlatformAttribution(user.id, sub.id, link2.id, acct2.id, strategy.code),
        "DUAL_2",
        net_pnl=70.0,
    )
    ledger = PlatformLedgerRepository(clean_db)
    t1 = await ledger.get_trades_for_strategy_accounts(user.id, [link1.id])
    t2 = await ledger.get_trades_for_strategy_accounts(user.id, [link2.id])
    assert compute_realized_from_trades(t1)["realized_pnl"] == pytest.approx(30.0)
    assert compute_realized_from_trades(t2)["realized_pnl"] == pytest.approx(70.0)


@pytest.mark.asyncio
async def test_combined_portfolio_no_double_counting(clean_db, vault):
    if not clean_db.is_connected:
        pytest.skip("Database not available")
    user, sub, account, link, strategy = await _seed_user_platform(vault, clean_db)
    platform = PlatformRepository(clean_db, vault)
    renko = await platform.get_strategy_by_code("renko_ichimoku_eth")
    if renko is None:
        renko = await platform.get_strategy_by_code("renko_ichimoku")
    sub_b = await platform.create_subscription(user.id, renko.id)
    link_b = await platform.link_strategy_account(subscription_id=sub_b.id, exchange_account_id=account.id)

    async with clean_db.get_session() as session:
        await session.execute(
            update(ExchangeAccountModel)
            .where(ExchangeAccountModel.id == account.id)
            .values(equity=1000.0, unrealized_pnl=50.0)
        )
        await session.commit()

    service = PlatformPerformanceService(
        PlatformLedgerRepository(clean_db),
        platform,
        SyncRepository(clean_db),
    )
    payload = await service.get_portfolio_performance(user.id, range_key="1M")
    assert payload["combined"]["total_equity"] == pytest.approx(1000.0)
    assert payload["architecture"]["combined_equity_source"] == "account_level"


@pytest.mark.asyncio
async def test_legacy_unattributed_trades_excluded(clean_db, vault):
    if not clean_db.is_connected:
        pytest.skip("Database not available")
    user, sub, account, link, strategy = await _seed_user_platform(vault, clean_db)
    async with clean_db.get_session() as session:
        await session.execute(
            text(
                """
                INSERT INTO trades (
                    trade_id, strategy_name, exchange, trade_date, status,
                    total_entry_premium, total_exit_premium, realized_pnl, total_fees, net_pnl
                ) VALUES (
                    'LEGACY_GLOBAL', 'short_strangle', 'delta_india', CURRENT_DATE, 'COMPLETED',
                    100, 50, 50, 0, 50
                )
                """
            )
        )
        await session.commit()

    ledger = PlatformLedgerRepository(clean_db)
    trades = await ledger.list_user_trades(user.id)
    assert all(t["trade_id"] != "LEGACY_GLOBAL" for t in trades)


@pytest.mark.asyncio
async def test_unauthorized_strategy_account_access(clean_db, vault):
    if not clean_db.is_connected:
        pytest.skip("Database not available")
    user_a, sub_a, account_a, link_a, _ = await _seed_user_platform(vault, clean_db, "user-a")
    user_b, _, _, _, _ = await _seed_user_platform(vault, clean_db, "user-b")
    ledger = PlatformLedgerRepository(clean_db)
    assert await ledger.verify_strategy_account_access(user_b.id, link_a.id) is None
    assert await ledger.verify_strategy_account_access(user_a.id, link_a.id) is not None


@pytest.mark.asyncio
async def test_empty_data_behavior(clean_db, vault):
    if not clean_db.is_connected:
        pytest.skip("Database not available")
    user, _, _, _, _ = await _seed_user_platform(vault, clean_db)
    service = PlatformPerformanceService(
        PlatformLedgerRepository(clean_db),
        PlatformRepository(clean_db, vault),
        SyncRepository(clean_db),
    )
    perf = await service.get_user_strategy_performance(user.id, "short_strangle")
    assert perf["available"] is False
    summary = compute_realized_from_trades([])
    assert summary["available"] is False


@pytest.mark.asyncio
async def test_performance_date_range_filter(clean_db, vault):
    if not clean_db.is_connected:
        pytest.skip("Database not available")
    user, sub, account, link, strategy = await _seed_user_platform(vault, clean_db)
    repo = TradeRepository(clean_db)
    attr = _attribution(user, sub, account, link, strategy)
    await _record_attributed_trade(repo, attr, "OLD_TRADE", net_pnl=10.0)

    async with clean_db.get_session() as session:
        await session.execute(
            update(TradeModel)
            .where(TradeModel.trade_id == "OLD_TRADE")
            .values(entry_time=datetime.now(timezone.utc) - timedelta(days=60))
        )
        await session.commit()

    ledger = PlatformLedgerRepository(clean_db)
    recent = await ledger.get_trades_for_strategy_accounts(
        user.id,
        [link.id],
        from_date=datetime.now(timezone.utc) - timedelta(days=30),
    )
    assert len(recent) == 0


def test_merge_equity_curves_no_double_count_per_account():
    curves = [
        [{"timestamp": "2026-01-01T00:00:00+00:00", "equity": 500}],
        [{"timestamp": "2026-01-01T00:00:00+00:00", "equity": 500}],
    ]
    merged = merge_equity_curves(curves)
    assert merged[0]["equity"] == pytest.approx(1000)
