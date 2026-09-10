"""Isolation, routing, and confirmed-brick tests for ETHUSDT Renko + Ichimoku."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List
from unittest.mock import AsyncMock

import pytest

from src.config.settings import Settings
from src.core.models.order import Order, OrderRequest
from src.engine import TradingEngine
from src.execution.order_manager import OrderManager
from src.strategies.renko_ichimoku.ichimoku import IncrementalIchimoku, IchimokuSnapshot
from src.strategies.renko_ichimoku.renko import TraditionalRenko, ConfirmedBrick
from src.strategies.renko_ichimoku.runtime import ClosedCandle, RenkoIchimokuRuntime
from src.strategies.renko_ichimoku.signals import evaluate_confirmed_brick
from src.strategies.short_strangle.strategy import BTCShortStrangleStrategy


def _settings(**kwargs) -> Settings:
    base = dict(
        _env_file=None,
        delta_testnet_api_key="k",
        delta_testnet_api_secret="s",
        db_enabled=False,
        reconciliation_interval_seconds=99999.0,
    )
    base.update(kwargs)
    return Settings(**base)


class StubExec:
    def __init__(self, account: str):
        self.account = account
        self.orders: List[OrderRequest] = []

    async def execute_order(self, request: OrderRequest) -> Order:
        self.orders.append(request)
        return Order(
            order_id=f"{self.account}-{len(self.orders)}",
            client_order_id=request.client_order_id,
            instrument_id=request.instrument_id,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            strategy_id=request.strategy_id,
            average_fill_price=100.0,
        )


class MemoryCandles:
    def __init__(self, candles: List[ClosedCandle]):
        self.candles = candles

    async def fetch_closed_candles(self, symbol: str, resolution: str, limit: int) -> List[ClosedCandle]:
        return list(self.candles)

    async def resolve_perpetual(self, symbol: str):
        return {
            "id": 42,
            "instrument_id": "42",
            "symbol": symbol,
            "contract_type": "perpetual_futures",
            "instrument_type": "perpetual",
            "exact_symbol_match": True,
        }


def _brick(direction: int, close: float, idx: int = 0) -> ConfirmedBrick:
    o = close - 15 if direction == 1 else close + 15
    return ConfirmedBrick(
        index=idx,
        timestamp=float(idx),
        open=o,
        high=max(o, close),
        low=min(o, close),
        close=close,
        direction=direction,
        source_bar_index=idx,
    )


def _ich(
    *,
    ready=True,
    above_cloud=False,
    below_cloud=False,
    inside_cloud=False,
    above_kijun=False,
    below_kijun=False,
    at_or_above_kijun=False,
) -> IchimokuSnapshot:
    return IchimokuSnapshot(
        index=80,
        tenkan=1.0,
        kijun=1.0,
        span_a=100.0,
        span_b=110.0,
        ready=ready,
        above_cloud=above_cloud,
        below_cloud=below_cloud,
        inside_cloud=inside_cloud,
        above_kijun=above_kijun,
        below_kijun=below_kijun,
        at_or_above_kijun=at_or_above_kijun,
    )


def test_defaults_do_not_enable_renko_or_change_strangle():
    s = _settings()
    assert s.existing_strategy_enabled is True
    assert s.renko_ichimoku_strategy_enabled is False
    assert s.order_quantity == 1.0
    assert s.renko_ichimoku_position_size == 0.0
    assert s.strategy == "short_strangle"
    assert s.underlying == "BTC"


def test_engine_keeps_short_strangle_when_renko_disabled():
    engine = TradingEngine(settings=_settings(renko_ichimoku_strategy_enabled=False))
    assert isinstance(engine.strategy, BTCShortStrangleStrategy)
    assert engine.renko_runtime is None
    assert engine.strategy.config.underlying == "BTC"
    assert engine.strategy.config.quantity == 1.0


def test_engine_wires_independent_managers_when_both_enabled():
    engine = TradingEngine(
        settings=_settings(
            existing_strategy_enabled=True,
            renko_ichimoku_strategy_enabled=True,
            existing_strategy_account="account_a",
            renko_ichimoku_account="account_a",
            renko_ichimoku_position_size=3,
        )
    )
    assert isinstance(engine.strategy, BTCShortStrangleStrategy)
    assert engine.renko_runtime is not None
    assert engine.renko_order_manager is not engine.order_manager
    assert engine.renko_execution is not engine.execution_engine
    assert engine.renko_runtime.position_size == 3
    assert engine.renko_runtime.account_name == engine.settings.renko_ichimoku_account


def test_separate_account_without_keys_does_not_start_renko():
    engine = TradingEngine(
        settings=_settings(
            existing_strategy_enabled=True,
            renko_ichimoku_strategy_enabled=True,
            existing_strategy_account="account_a",
            renko_ichimoku_account="account_b",
            renko_ichimoku_api_key="",
            renko_ichimoku_api_secret="",
        )
    )
    assert engine.renko_runtime is None
    assert isinstance(engine.strategy, BTCShortStrangleStrategy)


@pytest.mark.asyncio
async def test_existing_disabled_does_not_call_strangle_timer():
    engine = TradingEngine(
        settings=_settings(existing_strategy_enabled=False, renko_ichimoku_strategy_enabled=False)
    )
    engine._running = True
    engine.strategy._active = True
    engine.strategy.on_timer = AsyncMock()
    await engine._on_timer_tick(datetime.now(timezone.utc))
    engine.strategy.on_timer.assert_not_called()


@pytest.mark.asyncio
async def test_existing_enabled_renko_disabled_calls_only_strangle_timer():
    engine = TradingEngine(
        settings=_settings(existing_strategy_enabled=True, renko_ichimoku_strategy_enabled=False)
    )
    engine._running = True
    engine.strategy._active = True
    engine.strategy.on_timer = AsyncMock()
    assert engine.renko_runtime is None
    await engine._on_timer_tick(datetime.now(timezone.utc))
    engine.strategy.on_timer.assert_awaited_once()


@pytest.mark.asyncio
async def test_both_enabled_timer_is_independent():
    engine = TradingEngine(
        settings=_settings(
            existing_strategy_enabled=True,
            renko_ichimoku_strategy_enabled=True,
            existing_strategy_account="a",
            renko_ichimoku_account="a",
        )
    )
    engine._running = True
    engine.strategy._active = True
    engine.strategy.on_timer = AsyncMock()
    engine.renko_runtime.on_timer = AsyncMock()
    await engine._on_timer_tick(datetime.now(timezone.utc))
    engine.strategy.on_timer.assert_awaited_once()
    engine.renko_runtime.on_timer.assert_awaited_once()


def test_renko_confirmed_closes_only_no_projection():
    r = TraditionalRenko(box_size=15.0)
    assert r.apply_close(100.0, 1.0) == []
    # 100 grids to 90; a $14 continuation is unconfirmed.
    assert r.apply_close(104.0, 2.0) == []
    bricks = r.apply_close(105.0, 3.0)
    assert len(bricks) == 1
    assert bricks[0].close == r.last_close
    assert bricks[0].direction == 1


def test_ichimoku_no_lookahead():
    ich = IncrementalIchimoku()
    r = TraditionalRenko(box_size=15.0)
    price = 1500.0
    snaps = []
    for i in range(90):
        price += 15.0
        bricks = r.apply_close(price, float(i))
        for b in bricks:
            snaps.append(ich.update(b))
    assert len(snaps) >= 78
    frozen = snaps[77]
    later = snaps[-1]
    assert later.index > frozen.index
    assert ich.snapshots[77] == frozen
    assert frozen.span_a == ich.span_a_raw[77 - 26]
    assert frozen.span_b == ich.span_b_raw[77 - 26]


def test_signals_exit_first_then_entry():
    brick = _brick(-1, 90.0)
    ich = _ich(inside_cloud=True, below_cloud=False, below_kijun=False)
    actions = evaluate_confirmed_brick(1, brick, ich)
    assert [a.kind for a in actions] == ["exit_long"]

    brick = _brick(1, 200.0)
    ich = _ich(at_or_above_kijun=True, above_cloud=True, above_kijun=True)
    actions = evaluate_confirmed_brick(-1, brick, ich)
    assert [a.kind for a in actions] == ["exit_short", "enter_long"]


def test_unready_ichimoku_no_signals():
    brick = _brick(1, 200.0)
    assert evaluate_confirmed_brick(0, brick, _ich(ready=False, above_cloud=True, above_kijun=True)) == []


def _runtime(tmp_path, exec_stub, candles, account="acct", size=1.0, **kwargs):
    store_path = str(tmp_path / f"{account}.json")
    src = MemoryCandles(candles)
    last = candles[-1].time if candles else 0.0
    return RenkoIchimokuRuntime(
        account_name=account,
        symbol="ETHUSDT",
        position_size=size,
        candle_resolution="15m",
        state_file=store_path,
        execution_engine=exec_stub,
        order_manager=OrderManager(),
        candle_source=src,
        product_source=src,
        logger=__import__("logging").getLogger(account),
        dry_run=False,
        now_fn=lambda: last + 901,
        **kwargs,
    )


def _trend_candles(n=120, start=1500.0, step=20.0):
    out = []
    px = start
    t = 1_700_000_000.0
    for i in range(n):
        px += step
        out.append(ClosedCandle(time=t + i * 900, close=px))
    return out


@pytest.mark.asyncio
async def test_restart_does_not_reopen_from_history(tmp_path):
    candles = _trend_candles()
    exec_a = StubExec("a")
    rt = _runtime(tmp_path, exec_a, candles, account="a", size=1.0)
    await rt.start()
    assert exec_a.orders == []
    assert rt.position == 0

    rt.state.position = 1
    rt.store.save(rt.state)
    exec_b = StubExec("a")
    rt2 = _runtime(tmp_path, exec_b, candles, account="a", size=1.0)
    await rt2.start()
    assert exec_b.orders == []
    assert rt2.position == 1


@pytest.mark.asyncio
async def test_new_confirmed_brick_after_warmup_can_order_once(tmp_path):
    hist = _trend_candles()
    exec_a = StubExec("acct_b")
    rt = _runtime(tmp_path, exec_a, hist, account="acct_b", size=2.0)
    await rt.start()
    assert exec_a.orders == []
    last_t = hist[-1].time
    last_px = hist[-1].close
    rt.candle_source.candles = hist + [ClosedCandle(time=last_t + 900, close=last_px + 20)]
    rt.now_fn = lambda: last_t + 900 + 901
    await rt.on_timer()
    n = len(exec_a.orders)
    assert n >= 1
    await rt.on_timer()
    assert len(exec_a.orders) == n
    for req in exec_a.orders:
        assert req.strategy_id == "renko_ichimoku"
        assert req.quantity == 2.0
        assert req.symbol == "ETHUSDT"


@pytest.mark.asyncio
async def test_positions_and_accounts_do_not_bleed(tmp_path):
    candles = _trend_candles()
    exec_a = StubExec("account_a")
    exec_b = StubExec("account_b")
    rt_a = _runtime(tmp_path, exec_a, candles, account="account_a", size=1.0)
    rt_b = _runtime(tmp_path, exec_b, candles, account="account_b", size=4.0)
    await rt_a.start()
    await rt_b.start()
    rt_a.state.position = 1
    rt_b.state.position = -1
    assert rt_a.position != rt_b.position
    assert rt_a.account_name != rt_b.account_name
    last_t = candles[-1].time
    last_px = candles[-1].close
    nxt = ClosedCandle(time=last_t + 900, close=last_px + 20)
    rt_a.candle_source.candles = candles + [nxt]
    rt_b.candle_source.candles = candles + [nxt]
    rt_a.now_fn = lambda: last_t + 900 + 901
    rt_b.now_fn = lambda: last_t + 900 + 901
    await rt_a.on_timer()
    await rt_b.on_timer()
    for req in exec_a.orders:
        assert req.quantity == 1.0
    for req in exec_b.orders:
        assert req.quantity == 4.0


def test_disabled_renko_does_not_change_strangle_quantity_or_times():
    engine = TradingEngine(settings=_settings(renko_ichimoku_strategy_enabled=False, order_quantity=5.0))
    assert engine.strategy.config.quantity == 5.0
    assert engine.strategy.config.target_premium == 100.0
    assert engine.renko_runtime is None


def test_separate_account_uses_renko_keys():
    engine = TradingEngine(
        settings=_settings(
            renko_ichimoku_strategy_enabled=True,
            existing_strategy_account="account_a",
            renko_ichimoku_account="account_b",
            renko_ichimoku_api_key="renko_key",
            renko_ichimoku_api_secret="renko_secret",
        )
    )
    assert engine.renko_adapter is not engine.delta_adapter
    assert engine.renko_adapter.rest_client.api_key == "renko_key"
    assert engine.delta_adapter.rest_client.api_key == "k"
