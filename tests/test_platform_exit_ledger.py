"""Phase 7 — exit fill attribution, idempotency, and multi-leg P&L tests."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from src.core.models.instrument import OptionType
from src.core.models.order import Fill, Order, OrderSide, OrderState, OrderType
from src.core.models.trade import LegStatus, StrategyLeg, StrategyState, StrategyTrade
from src.persistence.models import FillModel, OrderModel
from src.persistence.trade_repository import TradeRepository
from src.platform.execution.lifecycle_repository import OrderLifecycleRepository
from src.platform.execution.models import ExecutionResult, OrderIntent, OrderLifecycleStatus
from src.platform.ledger.models import PlatformAttribution
from src.platform.ledger.pnl import compute_leg_realized_pnl
from src.platform.persistence.exit_ledger import PlatformExitLedger
from src.platform.persistence.fill_bridge import PlatformFillBridge
from src.platform.ledger.repository import PlatformLedgerRepository
from src.platform.repositories.platform_repository import PlatformRepository
from tests.test_platform_ledger import _attribution, _record_attributed_trade, _seed_user_platform, vault


def _strangle_trade(trade_id: str = "STRANGLE_P7") -> StrategyTrade:
    now = datetime.now(timezone.utc).isoformat()
    return StrategyTrade(
        strategy_trade_id=trade_id,
        strategy_name="short_strangle",
        trade_date=datetime.now(timezone.utc).date().isoformat(),
        state=StrategyState.ACTIVE,
        ce_leg=StrategyLeg(
            leg_id=f"{trade_id}_CE",
            option_type=OptionType.CALL,
            instrument_id="101",
            symbol="C-BTC-98000",
            strike=98000.0,
            expiry_date=datetime.now(timezone.utc).date().isoformat(),
            quantity=1.0,
            intended_premium=100.0,
            contract_value=1.0,
            entry_timestamp=now,
            entry_fill_price=100.0,
            status=LegStatus.OPEN,
        ),
        pe_leg=StrategyLeg(
            leg_id=f"{trade_id}_PE",
            option_type=OptionType.PUT,
            instrument_id="201",
            symbol="P-BTC-92000",
            strike=92000.0,
            expiry_date=datetime.now(timezone.utc).date().isoformat(),
            quantity=1.0,
            intended_premium=120.0,
            contract_value=1.0,
            entry_timestamp=now,
            entry_fill_price=120.0,
            status=LegStatus.OPEN,
        ),
    )


def _exit_result(client_id: str, price: float, qty: float = 1.0, intent_id=None) -> ExecutionResult:
    return ExecutionResult(
        success=True,
        status=OrderLifecycleStatus.FILLED,
        client_order_id=client_id,
        exchange_order_id=f"EX_{client_id}",
        filled_quantity=qty,
        average_price=price,
        order_intent_id=intent_id,
        fee=1.0,
    )


@pytest.mark.asyncio
async def test_normal_exit_attribution(clean_db, vault):
    if not clean_db.is_connected:
        pytest.skip("Database not available")
    user, sub, account, link, strategy = await _seed_user_platform(vault, clean_db)
    repo = TradeRepository(clean_db)
    attr = _attribution(user, sub, account, link, strategy)
    trade = _strangle_trade("EXIT_NORMAL")
    await _record_attributed_trade(repo, attr, "EXIT_NORMAL", net_pnl=0)

    lifecycle = OrderLifecycleRepository(clean_db)
    intent_id = await lifecycle.create_intent(
        strategy_account_id=link.id,
        runtime_id=None,
        intent=OrderIntent(
            signal_key="exit_ce",
            client_order_id="exit_ce_coid",
            symbol=trade.ce_leg.symbol,
            side="buy",
            quantity=1.0,
        ),
        execution_mode="PAPER",
        status=OrderLifecycleStatus.FILLED,
        leg_role="EXIT",
    )
    bridge = PlatformFillBridge(repo, PlatformLedgerRepository(clean_db))
    exit_ledger = PlatformExitLedger(
        context=type("Ctx", (), {
            "user_id": user.id,
            "subscription_id": sub.id,
            "strategy_account_id": link.id,
            "exchange_account_id": account.id,
            "strategy_code": strategy.code,
        })(),
        strategy=None,
        fill_bridge=bridge,
        lifecycle_repo=lifecycle,
        trade_repository=repo,
    )
    result = _exit_result("exit_ce_coid", 40.0, intent_id=intent_id)
    applied = await exit_ledger.persist_exit(
        trade=trade,
        leg=trade.ce_leg,
        result=result,
        exit_reason="EOD_EXIT",
        fee=1.0,
    )
    assert applied is True

    async with clean_db.get_session() as session:
        orders = list((await session.execute(select(OrderModel))).scalars().all())
        fills = list((await session.execute(select(FillModel))).scalars().all())
    assert any(o.strategy_order_intent_id == intent_id for o in orders)
    assert any(f.strategy_order_intent_id == intent_id for f in fills)
    assert trade.ce_leg.realized_pnl == pytest.approx(59.0)  # (100-40)*1 - 1 fee via on_leg_closed path skipped; direct calc 60-1=59? 
    # strategy=None path: (100-40)*1 - 1 = 59


@pytest.mark.asyncio
async def test_duplicate_fill_idempotency(clean_db, vault):
    if not clean_db.is_connected:
        pytest.skip("Database not available")
    user, sub, account, link, strategy = await _seed_user_platform(vault, clean_db)
    repo = TradeRepository(clean_db)
    attr = _attribution(user, sub, account, link, strategy)
    trade = _strangle_trade("EXIT_DUP")
    await _record_attributed_trade(repo, attr, "EXIT_DUP", net_pnl=0)
    lifecycle = OrderLifecycleRepository(clean_db)
    bridge = PlatformFillBridge(repo, PlatformLedgerRepository(clean_db))
    exit_ledger = PlatformExitLedger(
        context=type("Ctx", (), {
            "user_id": user.id,
            "subscription_id": sub.id,
            "strategy_account_id": link.id,
            "exchange_account_id": account.id,
            "strategy_code": strategy.code,
        })(),
        strategy=None,
        fill_bridge=bridge,
        lifecycle_repo=lifecycle,
        trade_repository=repo,
    )
    result = _exit_result("dup_exit", 50.0)
    assert await exit_ledger.persist_exit(trade=trade, leg=trade.ce_leg, result=result, exit_reason="STOP_LOSS") is True
    assert await exit_ledger.persist_exit(trade=trade, leg=trade.ce_leg, result=result, exit_reason="STOP_LOSS") is False
    async with clean_db.get_session() as session:
        fill_count = len(list((await session.execute(select(FillModel))).scalars().all()))
    assert fill_count == 3  # 2 entry + 1 exit


def test_multi_leg_strangle_pnl_ce100_pe120_exits():
    """CE entry 100 exit 40 (+60), PE entry 120 exit 150 (-30), total gross +30 before fees."""
    ce = compute_leg_realized_pnl(
        side="sell",
        entry_qty=Decimal("1"),
        exit_qty=Decimal("1"),
        entry_price=Decimal("100"),
        exit_price=Decimal("40"),
        fees=Decimal("0"),
    )
    pe = compute_leg_realized_pnl(
        side="sell",
        entry_qty=Decimal("1"),
        exit_qty=Decimal("1"),
        entry_price=Decimal("120"),
        exit_price=Decimal("150"),
        fees=Decimal("0"),
    )
    assert ce == Decimal("60")
    assert pe == Decimal("-30")
    assert ce + pe == Decimal("30")


@pytest.mark.asyncio
async def test_partial_exit_keeps_leg_open(clean_db, vault):
    if not clean_db.is_connected:
        pytest.skip("Database not available")
    user, sub, account, link, strategy = await _seed_user_platform(vault, clean_db)
    repo = TradeRepository(clean_db)
    attr = _attribution(user, sub, account, link, strategy)
    trade = _strangle_trade("PARTIAL")
    trade.ce_leg.quantity = 4.0
    await _record_attributed_trade(repo, attr, "PARTIAL", net_pnl=0)
    lifecycle = OrderLifecycleRepository(clean_db)
    bridge = PlatformFillBridge(repo)
    exit_ledger = PlatformExitLedger(
        context=type("Ctx", (), {
            "user_id": user.id,
            "subscription_id": sub.id,
            "strategy_account_id": link.id,
            "exchange_account_id": account.id,
            "strategy_code": strategy.code,
        })(),
        strategy=None,
        fill_bridge=bridge,
        lifecycle_repo=lifecycle,
        trade_repository=repo,
    )
    result = _exit_result("partial_1", 90.0, qty=1.0)
    await exit_ledger.persist_exit(trade=trade, leg=trade.ce_leg, result=result, exit_reason="EOD_EXIT", fee=0.5)
    assert trade.ce_leg.status == LegStatus.OPEN
    assert trade.ce_leg.quantity == pytest.approx(3.0)
    assert trade.ce_leg.realized_pnl == pytest.approx(9.5)  # (100-90)*1 - 0.5


@pytest.mark.asyncio
async def test_order_intent_propagation_to_order_and_fill(clean_db, vault):
    if not clean_db.is_connected:
        pytest.skip("Database not available")
    user, sub, account, link, strategy = await _seed_user_platform(vault, clean_db)
    repo = TradeRepository(clean_db)
    lifecycle = OrderLifecycleRepository(clean_db)
    intent_id = await lifecycle.create_intent(
        strategy_account_id=link.id,
        runtime_id=None,
        intent=OrderIntent(signal_key="k", client_order_id="entry_ce", symbol="C", side="sell", quantity=1),
        execution_mode="PAPER",
    )
    attr = _attribution(user, sub, account, link, strategy).with_intent(intent_id)
    await repo.upsert_trade(
        StrategyTrade(
            strategy_trade_id="T1",
            strategy_name="short_strangle",
            trade_date=datetime.now(timezone.utc).date().isoformat(),
            state=StrategyState.ACTIVE,
            ce_leg=StrategyLeg(
                leg_id="L1",
                option_type=OptionType.CALL,
                instrument_id="101",
                symbol="C",
                strike=1.0,
                expiry_date=datetime.now(timezone.utc).date().isoformat(),
                quantity=1.0,
                intended_premium=100.0,
            ),
        ),
        attribution=attr,
    )
    await repo.upsert_leg(
        StrategyLeg(
            leg_id="L1",
            option_type=OptionType.CALL,
            instrument_id="101",
            symbol="C",
            strike=1.0,
            expiry_date=datetime.now(timezone.utc).date().isoformat(),
            quantity=1.0,
            intended_premium=100.0,
        ),
        trade_id="T1",
    )
    order = Order(
        order_id="ORD_TEST",
        client_order_id="entry_ce",
        instrument_id="101",
        symbol="C",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=1,
        filled_quantity=1,
        average_fill_price=100,
        state=OrderState.FILLED,
    )
    db_id = await repo.upsert_order(order, trade_id="T1", leg_id="L1", attribution=attr, strategy_order_intent_id=intent_id)
    fill = Fill(fill_id="F1", order_id=db_id, client_order_id="entry_ce", instrument_id="101", symbol="C", side=OrderSide.SELL, quantity=1, price=100, fee=0)
    await repo.upsert_fill(fill, order_id=db_id, attribution=attr, strategy_order_intent_id=intent_id)
    async with clean_db.get_session() as session:
        o = (await session.execute(select(OrderModel).where(OrderModel.order_id == db_id))).scalar_one()
        f = (await session.execute(select(FillModel).where(FillModel.fill_id == "F1"))).scalar_one()
    assert o.strategy_order_intent_id == intent_id
    assert f.strategy_order_intent_id == intent_id


@pytest.mark.asyncio
async def test_emergency_unwind_exit_reason(clean_db, vault):
    if not clean_db.is_connected:
        pytest.skip("Database not available")
    user, sub, account, link, strategy = await _seed_user_platform(vault, clean_db)
    repo = TradeRepository(clean_db)
    attr = _attribution(user, sub, account, link, strategy)
    trade = _strangle_trade("UNWIND")
    trade.ce_leg.entry_fill_price = 100.0
    trade.ce_leg.contract_value = 1.0
    await repo.upsert_trade(trade, attribution=attr)
    await repo.upsert_leg(trade.ce_leg, trade_id=trade.strategy_trade_id)
    lifecycle = OrderLifecycleRepository(clean_db)
    bridge = PlatformFillBridge(repo)
    exit_ledger = PlatformExitLedger(
        context=type("Ctx", (), {
            "user_id": user.id,
            "subscription_id": sub.id,
            "strategy_account_id": link.id,
            "exchange_account_id": account.id,
            "strategy_code": strategy.code,
        })(),
        strategy=None,
        fill_bridge=bridge,
        lifecycle_repo=lifecycle,
        trade_repository=repo,
    )
    result = _exit_result("unwind_coid", 105.0)
    await exit_ledger.persist_exit(trade=trade, leg=trade.ce_leg, result=result, exit_reason="EMERGENCY_UNWIND", fee=0)
    assert trade.ce_leg.status == LegStatus.UNWOUND_ON_FAILURE
    assert trade.ce_leg.realized_pnl == pytest.approx(-5.0)


@pytest.mark.asyncio
async def test_unauthorized_cross_user_strategy_account(clean_db, vault):
    if not clean_db.is_connected:
        pytest.skip("Database not available")
    user_a, _, _, link_a, _ = await _seed_user_platform(vault, clean_db, "ua")
    user_b, _, _, _, _ = await _seed_user_platform(vault, clean_db, "ub")
    ledger = PlatformLedgerRepository(clean_db)
    assert await ledger.verify_strategy_account_access(user_b.id, link_a.id) is None
    assert await ledger.verify_strategy_account_access(user_a.id, link_a.id) is not None
