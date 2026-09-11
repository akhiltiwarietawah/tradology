"""Safety tests for Renko Ichimoku order/fill/reconcile fail-closed behavior."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from unittest.mock import AsyncMock

import pytest

from src.core.models.order import Order, OrderRequest, OrderState, OrderSide, OrderType
from src.core.models.position import Position
from src.execution.order_manager import OrderManager
from src.strategies.renko_ichimoku.runtime import ClosedCandle, RenkoIchimokuRuntime
from src.strategies.renko_ichimoku.state import RenkoIchimokuState, RenkoIchimokuStateStore
from tests.test_renko_ichimoku import (
    MemoryCandles,
    StubExec,
    _runtime,
    _settings,
    _trend_candles,
)
from src.engine import TradingEngine


class RejectExec:
    def __init__(self):
        self.orders: List[OrderRequest] = []

    async def execute_order(self, request: OrderRequest) -> Order:
        self.orders.append(request)
        return Order(
            order_id="rej-1",
            client_order_id=request.client_order_id,
            instrument_id=request.instrument_id,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            filled_quantity=0.0,
            state=OrderState.REJECTED,
            strategy_id="renko_ichimoku",
        )


class RaiseExec:
    def __init__(self):
        self.calls = 0

    async def execute_order(self, request: OrderRequest) -> Order:
        self.calls += 1
        raise TimeoutError("simulated timeout after submit")


class PartialExec:
    async def execute_order(self, request: OrderRequest) -> Order:
        return Order(
            order_id="p1",
            client_order_id=request.client_order_id,
            instrument_id=request.instrument_id,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            filled_quantity=max(request.quantity - 1, 0.5),
            state=OrderState.PARTIALLY_FILLED,
            strategy_id="renko_ichimoku",
            average_fill_price=100.0,
        )


class FakeExchange:
    def __init__(self, size: float = 0.0, symbol: str = "ETHUSDT", instrument_id: str = "42"):
        self.size = size
        self.symbol = symbol
        self.instrument_id = instrument_id
        self.orders_by_cid = {}

    async def get_positions(self) -> List[Position]:
        return [
            Position(
                instrument_id=self.instrument_id,
                symbol=self.symbol,
                size=self.size,
                raw_data={"side": "buy" if self.size > 0 else ("sell" if self.size < 0 else "")},
            )
        ]

    async def get_order_by_client_id(self, client_order_id: str) -> Optional[Order]:
        return self.orders_by_cid.get(client_order_id)


@pytest.mark.asyncio
async def test_rejected_order_does_not_update_position(tmp_path):
    hist = _trend_candles()
    exec_r = RejectExec()
    rt = _runtime(tmp_path, exec_r, hist, account="rej", size=1.0)
    await rt.start()
    last_t, last_px = hist[-1].time, hist[-1].close
    rt.candle_source.candles = hist + [ClosedCandle(time=last_t + 900, close=last_px + 20)]
    rt.now_fn = lambda: last_t + 1801
    await rt.on_timer()
    assert rt.position == 0
    assert rt.state.orders_halted is True
    n = len(exec_r.orders)
    await rt.on_timer()
    assert len(exec_r.orders) == n


@pytest.mark.asyncio
async def test_submit_exception_does_not_retry_new_order(tmp_path):
    hist = _trend_candles()
    exec_r = RaiseExec()
    rt = _runtime(tmp_path, exec_r, hist, account="to", size=1.0)
    await rt.start()
    last_t, last_px = hist[-1].time, hist[-1].close
    rt.candle_source.candles = hist + [ClosedCandle(time=last_t + 900, close=last_px + 20)]
    rt.now_fn = lambda: last_t + 1801
    await rt.on_timer()
    assert exec_r.calls == 1
    assert rt.position == 0
    assert rt.state.orders_halted is True
    assert rt.state.in_flight_client_order_id is not None
    await rt.on_timer()
    assert exec_r.calls == 1


@pytest.mark.asyncio
async def test_partial_fill_halts(tmp_path):
    hist = _trend_candles()
    rt = _runtime(tmp_path, PartialExec(), hist, account="part", size=2.0)
    await rt.start()
    last_t, last_px = hist[-1].time, hist[-1].close
    rt.candle_source.candles = hist + [ClosedCandle(time=last_t + 900, close=last_px + 20)]
    rt.now_fn = lambda: last_t + 1801
    await rt.on_timer()
    assert rt.state.orders_halted is True


@pytest.mark.asyncio
async def test_size_zero_never_orders(tmp_path):
    hist = _trend_candles()
    exec_a = StubExec("z")
    rt = _runtime(tmp_path, exec_a, hist, account="zero", size=0.0)
    await rt.start()
    last_t, last_px = hist[-1].time, hist[-1].close
    rt.candle_source.candles = hist + [ClosedCandle(time=last_t + 900, close=last_px + 20)]
    rt.now_fn = lambda: last_t + 1801
    await rt.on_timer()
    assert exec_a.orders == []
    assert rt.position == 0


@pytest.mark.asyncio
async def test_non_integer_size_halts_without_start_trading(tmp_path):
    hist = _trend_candles()
    exec_a = StubExec("n")
    rt = _runtime(tmp_path, exec_a, hist, account="frac", size=1.5)
    await rt.start()
    assert rt.state.orders_halted is True
    assert rt._started is False
    await rt.on_timer()
    assert exec_a.orders == []


@pytest.mark.asyncio
async def test_mismatch_local_flat_exchange_long_halts(tmp_path):
    hist = _trend_candles()
    exec_a = StubExec("m")
    fake = FakeExchange(size=1.0)
    rt = _runtime(tmp_path, exec_a, hist, account="mis", size=1.0, exchange_ops=fake)
    await rt.start()
    assert rt.state.orders_halted is True
    await rt.on_timer()
    assert exec_a.orders == []


@pytest.mark.asyncio
async def test_mismatch_local_long_exchange_flat_halts(tmp_path):
    hist = _trend_candles()
    store_path = tmp_path / "mlong.json"
    RenkoIchimokuStateStore(str(store_path), __import__("logging").getLogger("t")).save(
        RenkoIchimokuState(position=1, instrument_id="42", symbol="ETHUSDT")
    )
    src = MemoryCandles(hist)
    exec_a = StubExec("m2")
    rt = RenkoIchimokuRuntime(
        account_name="m2",
        symbol="ETHUSDT",
        position_size=1.0,
        candle_resolution="15m",
        state_file=str(store_path),
        execution_engine=exec_a,
        order_manager=OrderManager(),
        candle_source=src,
        product_source=src,
        logger=__import__("logging").getLogger("m2"),
        exchange_ops=FakeExchange(size=0.0),
        now_fn=lambda: hist[-1].time + 901,
    )
    await rt.start()
    assert rt.position == 1
    assert rt.state.orders_halted is True
    await rt.on_timer()
    assert exec_a.orders == []


@pytest.mark.asyncio
async def test_in_flight_recovery_applies_fill_and_does_not_reopen(tmp_path):
    hist = _trend_candles()
    cid = "RI0EL"
    filled = Order(
        order_id="ex-9",
        client_order_id=cid,
        instrument_id="42",
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=1.0,
        filled_quantity=1.0,
        state=OrderState.FILLED,
        average_fill_price=2000.0,
        strategy_id="renko_ichimoku",
    )
    fake = FakeExchange(size=1.0)
    fake.orders_by_cid[cid] = filled
    store_path = tmp_path / "inf.json"
    RenkoIchimokuStateStore(str(store_path), __import__("logging").getLogger("t")).save(
        RenkoIchimokuState(
            position=0,
            in_flight_client_order_id=cid,
            in_flight_action="enter_long",
            in_flight_brick_index=80,
            instrument_id="42",
        )
    )
    src = MemoryCandles(hist)
    exec_a = StubExec("inf")
    rt = RenkoIchimokuRuntime(
        account_name="inf",
        symbol="ETHUSDT",
        position_size=1.0,
        candle_resolution="15m",
        state_file=str(store_path),
        execution_engine=exec_a,
        order_manager=OrderManager(),
        candle_source=src,
        product_source=src,
        logger=__import__("logging").getLogger("inf"),
        exchange_ops=fake,
        now_fn=lambda: hist[-1].time + 901,
    )
    await rt.start()
    assert rt.position == 1
    assert rt.state.in_flight_client_order_id is None
    assert exec_a.orders == []


@pytest.mark.asyncio
async def test_flatten_sends_reduce_only_and_halts(tmp_path):
    hist = _trend_candles()
    exec_a = StubExec("fl")
    fake = FakeExchange(size=2.0)
    rt = _runtime(tmp_path, exec_a, hist, account="fl", size=2.0, exchange_ops=fake, flatten=True)
    await rt.start()
    assert len(exec_a.orders) == 1
    assert exec_a.orders[0].reduce_only is True
    assert exec_a.orders[0].side.value == "sell"
    assert exec_a.orders[0].quantity == 2.0
    assert rt.position == 0
    assert rt.state.orders_halted is True
    await rt.on_timer()
    assert len(exec_a.orders) == 1


def test_corrupt_state_starts_flat(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not-json", encoding="utf-8")
    st = RenkoIchimokuStateStore(str(p), __import__("logging").getLogger("t")).load()
    assert st.position == 0
    assert st.in_flight_client_order_id is None


def test_disabled_renko_does_not_construct_runtime():
    engine = TradingEngine(
        settings=_settings(existing_strategy_enabled=True, renko_ichimoku_strategy_enabled=False)
    )
    assert engine.renko_runtime is None


@pytest.mark.asyncio
async def test_candle_fetch_error_skips_orders(tmp_path):
    hist = _trend_candles()
    exec_a = StubExec("cf")
    rt = _runtime(tmp_path, exec_a, hist, account="cf", size=1.0)
    await rt.start()
    rt.candle_source.fetch_closed_candles = AsyncMock(side_effect=ConnectionError("down"))
    await rt.on_timer()
    assert exec_a.orders == []
    assert rt.state.orders_halted is False


@pytest.mark.asyncio
async def test_transient_reconcile_halt_recovers_on_next_success(tmp_path):
    hist = _trend_candles()
    exec_a = StubExec("recover")
    fake = FakeExchange(size=0.0)
    store_path = tmp_path / "recover.json"
    RenkoIchimokuStateStore(str(store_path), __import__("logging").getLogger("t")).save(
        RenkoIchimokuState(
            position=0,
            instrument_id="42",
            symbol="ETHUSDT",
            orders_halted=True,
            halt_reason="Could not read exchange positions for reconcile. Trading halted.",
        )
    )
    src = MemoryCandles(hist)
    rt = RenkoIchimokuRuntime(
        account_name="recover",
        symbol="ETHUSDT",
        position_size=1.0,
        candle_resolution="15m",
        state_file=str(store_path),
        execution_engine=exec_a,
        order_manager=OrderManager(),
        candle_source=src,
        product_source=src,
        logger=__import__("logging").getLogger("recover"),
        exchange_ops=fake,
        now_fn=lambda: hist[-1].time + 901,
    )
    await rt.start()
    assert rt.state.orders_halted is False
    assert rt._trading_unlocked is True


@pytest.mark.asyncio
async def test_runtime_position_drift_halts_on_timer(tmp_path):
    hist = _trend_candles()
    exec_a = StubExec("drift")
    fake = FakeExchange(size=1.0)
    store_path = tmp_path / "drift.json"
    RenkoIchimokuStateStore(str(store_path), __import__("logging").getLogger("t")).save(
        RenkoIchimokuState(position=1, instrument_id="42", symbol="ETHUSDT")
    )
    src = MemoryCandles(hist)
    rt = RenkoIchimokuRuntime(
        account_name="drift",
        symbol="ETHUSDT",
        position_size=1.0,
        candle_resolution="15m",
        state_file=str(store_path),
        execution_engine=exec_a,
        order_manager=OrderManager(),
        candle_source=src,
        product_source=src,
        logger=__import__("logging").getLogger("drift"),
        exchange_ops=fake,
        now_fn=lambda: hist[-1].time + 901,
    )
    await rt.start()
    assert rt.state.orders_halted is False
    assert rt.position == 1
    fake.size = 0.0
    rt._last_position_reconcile_ts = 0.0
    await rt.on_timer()
    assert rt.state.orders_halted is True
    assert exec_a.orders == []


@pytest.mark.asyncio
async def test_engine_syncs_runtime_kill_switch_on_timer():
    engine = TradingEngine(
        settings=_settings(
            existing_strategy_enabled=False,
            renko_ichimoku_strategy_enabled=True,
            renko_ichimoku_account="a",
            existing_strategy_account="a",
        )
    )
    assert engine.renko_runtime.kill_switch is False
    engine._running = True
    engine.renko_runtime.on_timer = AsyncMock()
    engine.risk_manager.activate_kill_switch()
    await engine._on_timer_tick(datetime.now(timezone.utc))
    assert engine.renko_runtime.kill_switch is True
    engine.renko_runtime.on_timer.assert_awaited_once()
