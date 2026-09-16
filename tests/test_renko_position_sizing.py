"""Unit tests for Renko dynamic position sizing."""

from __future__ import annotations

import pytest

from src.strategies.renko_ichimoku.position_sizing import (
    apply_exit_to_sizing_equity,
    compute_realized_pnl_usd,
    contracts_from_sizing_equity,
    effective_equity_for_entry,
    margin_usd_from_equity,
)


def test_realized_pnl_long_and_short():
    assert compute_realized_pnl_usd(100.0, 110.0, 10, 0.01, 1) == pytest.approx(1.0)
    assert compute_realized_pnl_usd(100.0, 90.0, 10, 0.01, -1) == pytest.approx(1.0)
    assert compute_realized_pnl_usd(100.0, 90.0, 10, 0.01, 1) == pytest.approx(-1.0)


def test_apply_exit_retains_half_of_profit_only():
    eq = apply_exit_to_sizing_equity(100.0, 20.0, 0.5)
    assert eq == pytest.approx(110.0)
    eq = apply_exit_to_sizing_equity(100.0, -20.0, 0.5)
    assert eq == pytest.approx(80.0)


def test_contracts_from_100_usd_account_25pct_10x():
    # $100 equity -> $25 margin -> $250 notional; ETH $3000, cv=0.01 -> $30/contract -> 8
    qty = contracts_from_sizing_equity(100.0, 0.25, 10.0, 3000.0, 0.01)
    assert qty == 8


def test_effective_equity_caps_virtual_by_account():
    assert effective_equity_for_entry(50.0, 100.0) == 50.0
    assert effective_equity_for_entry(0.0, 50.0) == 50.0
    assert effective_equity_for_entry(80.0, None) == 80.0


def test_margin_per_trade_25pct_of_50_account():
    margin, notional = margin_usd_from_equity(50.0, 0.25, 10.0)
    assert margin == pytest.approx(12.5)
    assert notional == pytest.approx(125.0)


def test_sol_contract_value_one_needs_more_notional():
    # SOL ~$140, cv=1 -> 1 contract = $140 notional; $125 notional -> 0 contracts
    qty = contracts_from_sizing_equity(50.0, 0.25, 10.0, 140.0, 1.0)
    assert qty == 0


@pytest.mark.asyncio
async def test_runtime_dynamic_sizing_updates_equity_on_exit(tmp_path):
    from src.core.models.order import Order, OrderSide, OrderState, OrderType
    from src.execution.order_manager import OrderManager
    from src.strategies.renko_ichimoku.runtime import RenkoIchimokuRuntime
    from tests.test_renko_ichimoku import MemoryCandles, StubExec, _trend_candles

    candles = _trend_candles()
    exec_stub = StubExec("dyn")
    rt = RenkoIchimokuRuntime(
        account_name="dyn",
        symbol="ETHUSDT",
        position_size=0,
        candle_resolution="15m",
        state_file=str(tmp_path / "dyn.json"),
        execution_engine=exec_stub,
        order_manager=OrderManager(),
        candle_source=MemoryCandles(candles),
        product_source=MemoryCandles(candles),
        logger=__import__("logging").getLogger("dyn"),
        dry_run=True,
        position_sizing_mode="dynamic",
        sizing_base_usd=100.0,
        margin_pct=0.25,
        leverage=10.0,
        profit_retain_pct=0.5,
        contract_value=0.01,
    )
    class _FakeOps:
        async def get_account_balances(self):
            class USD:
                available_balance = 100.0

            class AB:
                balances = {"USD": USD()}

            return AB()

    rt.exchange_ops = _FakeOps()

    await rt.start()
    assert rt.state.sizing_equity == pytest.approx(100.0)

    brick = __import__(
        "src.strategies.renko_ichimoku.renko", fromlist=["ConfirmedBrick"]
    ).ConfirmedBrick(1, 0, 0, 0, 0, 3000.0, 1, 0)
    entry_qty = await rt._quantity_for_action("enter_long", brick)
    assert entry_qty == 8.0

    rt.state.position = 1
    rt.state.entry_price = 3000.0
    rt.state.open_quantity = entry_qty
    order = Order(
        order_id="x1",
        client_order_id="c1",
        instrument_id="42",
        symbol="ETHUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=entry_qty,
        filled_quantity=entry_qty,
        state=OrderState.FILLED,
        average_fill_price=3010.0,
    )
    brick = __import__(
        "src.strategies.renko_ichimoku.renko", fromlist=["ConfirmedBrick"]
    ).ConfirmedBrick(2, 0, 0, 0, 0, 3010.0, -1, 1)
    rt._pending_order_quantity = entry_qty
    rt._apply_fill("exit_long", order, brick)
    # pnl = (3010-3000)*8*0.01 = 0.8; retain 50% -> +0.4
    assert rt.state.sizing_equity == pytest.approx(100.4)
    assert rt.state.last_realized_pnl == pytest.approx(0.8)
