"""Pytest fixtures and mock objects for trading engine tests."""

import pytest
from datetime import datetime, date, time, timezone
from typing import Dict, List, Optional, Any, Callable, Awaitable

from src.config.settings import Settings, Environment
from src.core.models.instrument import Instrument, OptionChain, InstrumentType, OptionType
from src.core.models.market_data import Ticker
from src.core.models.order import Order, OrderRequest, OrderSide, OrderType, OrderState
from src.core.models.position import Position
from src.core.models.trade import StrategyTrade, StrategyLeg, StrategyState, LegStatus
from src.core.interfaces.exchange import BaseExchangeAdapter


class MockExchangeAdapter(BaseExchangeAdapter):
    """Configurable mock exchange adapter for testing."""

    def __init__(self):
        self._exchange_name = "mock_delta"
        self._connected = True
        self.spot_price = 95000.0
        self.instruments: List[Instrument] = []
        self.tickers_map: Dict[str, Ticker] = {}
        self.positions: List[Position] = []
        self.orders: Dict[str, Order] = {}
        self.placed_orders: List[OrderRequest] = []
        self.fail_order_placement = False
        self.fail_specific_symbol: Optional[str] = None

    @property
    def exchange_name(self) -> str:
        return self._exchange_name

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def initialize(self) -> bool:
        return True

    async def close(self) -> None:
        self._connected = False

    async def get_spot_price(self, underlying: str = "BTC") -> float:
        return self.spot_price

    async def get_instruments(
        self,
        underlying: Optional[str] = None,
        instrument_type: Optional[InstrumentType] = None,
    ) -> List[Instrument]:
        res = self.instruments
        if underlying:
            res = [i for i in res if i.underlying.upper() == underlying.upper()]
        if instrument_type:
            res = [i for i in res if i.instrument_type == instrument_type]
        return res

    async def get_option_chain(self, underlying: str, expiry_date: date) -> OptionChain:
        calls = [i for i in self.instruments if i.is_call and (not i.expiry or i.expiry.date() == expiry_date)]
        puts = [i for i in self.instruments if i.is_put and (not i.expiry or i.expiry.date() == expiry_date)]
        return OptionChain(exchange=self.exchange_name, underlying=underlying, expiry_date=expiry_date, calls=calls, puts=puts)

    async def get_tickers(self, symbols_or_ids: Optional[List[str]] = None) -> Dict[str, Ticker]:
        return self.tickers_map

    async def get_positions(self) -> List[Position]:
        if self.fail_specific_symbol == "FAIL_ALL":
            raise RuntimeError("Delta API HTTP 401: ip_not_whitelisted_for_api_key")
        return self.positions

    async def get_open_orders(self, instrument_id: Optional[str] = None) -> List[Order]:
        return list(self.orders.values())

    async def get_order_by_client_id(self, client_order_id: str) -> Optional[Order]:
        for o in self.orders.values():
            if o.client_order_id == client_order_id:
                return o
        return None

    async def place_order(self, order_request: OrderRequest) -> Order:
        self.placed_orders.append(order_request)

        if self.fail_order_placement:
            raise RuntimeError("Simulated exchange order placement failure")

        if self.fail_specific_symbol and order_request.symbol == self.fail_specific_symbol:
            raise RuntimeError(f"Simulated failure for symbol {order_request.symbol}")

        order_id = f"ORD_{len(self.orders) + 1}"
        order = Order(
            order_id=order_id,
            client_order_id=order_request.client_order_id,
            instrument_id=order_request.instrument_id,
            symbol=order_request.symbol,
            side=order_request.side,
            order_type=order_request.order_type,
            quantity=order_request.quantity,
            price=order_request.price,
            state=OrderState.FILLED,
            filled_quantity=order_request.quantity,
            average_fill_price=order_request.price or 100.0,
            strategy_id=order_request.strategy_id,
            leg_id=order_request.leg_id,
        )
        self.orders[order_id] = order

        # Update mock positions
        size_delta = order_request.quantity if order_request.side == OrderSide.BUY else -order_request.quantity
        found = False
        for p in self.positions:
            if p.symbol == order_request.symbol:
                p.size += size_delta
                found = True
                break
        if not found:
            self.positions.append(
                Position(
                    instrument_id=order_request.instrument_id,
                    symbol=order_request.symbol,
                    size=size_delta,
                    entry_price=order_request.price or 100.0,
                )
            )

        return order

    async def cancel_order(self, order_id: str, instrument_id: str) -> bool:
        if order_id in self.orders:
            self.orders[order_id].state = OrderState.CANCELLED
            return True
        return False

    async def cancel_all_orders(self, instrument_id: Optional[str] = None) -> bool:
        for o in self.orders.values():
            o.state = OrderState.CANCELLED
        return True

    async def subscribe_market_data(self, symbols: List[str], callback: Callable[[Ticker], Awaitable[None]]) -> None:
        pass

    async def subscribe_private_events(self, order_callback=None, position_callback=None) -> None:
        pass

    async def get_account_balances(self) -> Any:
        from src.core.models.account import AssetBalance, AccountBalance
        return AccountBalance(
            balances={
                "USD": AssetBalance(asset_symbol="USD", balance=1000.0, available_balance=1000.0, balance_inr=86500.0),
                "INR": AssetBalance(asset_symbol="INR", balance=10000.0, available_balance=10000.0),
                "BTC": AssetBalance(asset_symbol="BTC", balance=0.05, available_balance=0.05),
            }
        )

    async def create_bracket_order(
        self,
        instrument_id: str,
        stop_loss_price: float,
        take_profit_price: Optional[float] = None,
        stop_trigger_method: str = "mark_price",
        order_type: str = "market_order",
    ) -> Dict[str, Any]:
        if getattr(self, "fail_bracket_creation", False):
            raise RuntimeError("Simulated bracket order creation failure")

        bracket_id = f"BRK_{instrument_id}_{int(stop_loss_price)}"
        order = Order(
            order_id=bracket_id,
            client_order_id=None,
            instrument_id=instrument_id,
            symbol=next((p.symbol for p in self.positions if p.instrument_id == instrument_id), f"OPT_{instrument_id}"),
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            price=stop_loss_price,
            state=OrderState.OPEN,
            raw_data={"bracket_order": True, "stop_order_type": "stop_loss_order", "stop_price": str(stop_loss_price), "take_profit_price": str(take_profit_price) if take_profit_price else None},
        )
        self.orders[bracket_id] = order
        return {"id": bracket_id, "product_id": instrument_id, "stop_price": stop_loss_price, "take_profit_price": take_profit_price}

    async def get_bracket_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        if order_id in self.orders:
            o = self.orders[order_id]
            return {"id": o.order_id, "product_id": o.instrument_id, "stop_price": o.price}
        return None

    async def get_recent_fills_for_product(
        self,
        instrument_id: str,
        side: Optional[str] = None,
        page_size: int = 10,
    ) -> List[Dict[str, Any]]:
        """Return test-configured fills keyed by instrument_id. Empty list by default."""
        fills_map: Dict[str, List[Dict]] = getattr(self, "fills_by_instrument", {})
        fills = fills_map.get(str(instrument_id), [])
        if side:
            fills = [f for f in fills if f.get("side", "").lower() == side.lower()]
        return fills[:page_size]


@pytest.fixture
def mock_exchange():
    adapter = MockExchangeAdapter()
    today = datetime.now(timezone.utc).date()
    today_str = today.strftime("%d%m%y")

    # Setup sample options instruments
    # OTM Calls (Strike > 95000)
    c96000 = Instrument(
        exchange="mock_delta",
        instrument_id="101",
        symbol=f"C-BTC-96000-{today_str}",
        underlying="BTC",
        instrument_type=InstrumentType.OPTION,
        option_type=OptionType.CALL,
        strike_price=96000.0,
        expiry=datetime.combine(today, time(17, 30)),
        contract_value=0.001,
        tick_size=0.1,
    )
    c98000 = Instrument(
        exchange="mock_delta",
        instrument_id="102",
        symbol=f"C-BTC-98000-{today_str}",
        underlying="BTC",
        instrument_type=InstrumentType.OPTION,
        option_type=OptionType.CALL,
        strike_price=98000.0,
        expiry=datetime.combine(today, time(17, 30)),
        contract_value=0.001,
        tick_size=0.1,
    )

    # OTM Puts (Strike < 95000)
    p94000 = Instrument(
        exchange="mock_delta",
        instrument_id="201",
        symbol=f"P-BTC-94000-{today_str}",
        underlying="BTC",
        instrument_type=InstrumentType.OPTION,
        option_type=OptionType.PUT,
        strike_price=94000.0,
        expiry=datetime.combine(today, time(17, 30)),
        contract_value=0.001,
        tick_size=0.1,
    )
    p92000 = Instrument(
        exchange="mock_delta",
        instrument_id="202",
        symbol=f"P-BTC-92000-{today_str}",
        underlying="BTC",
        instrument_type=InstrumentType.OPTION,
        option_type=OptionType.PUT,
        strike_price=92000.0,
        expiry=datetime.combine(today, time(17, 30)),
        contract_value=0.001,
        tick_size=0.1,
    )

    adapter.instruments = [c96000, c98000, p94000, p92000]

    # Setup tickers
    # c98000 is closest to $100 (e.g. $98.50)
    # p92000 is closest to $100 (e.g. $102.00)
    adapter.tickers_map = {
        c96000.symbol: Ticker(symbol=c96000.symbol, instrument_id=c96000.instrument_id, mark_price=250.0, best_bid=245.0, best_ask=255.0),
        c98000.symbol: Ticker(symbol=c98000.symbol, instrument_id=c98000.instrument_id, mark_price=98.5, best_bid=98.0, best_ask=99.0),
        p94000.symbol: Ticker(symbol=p94000.symbol, instrument_id=p94000.instrument_id, mark_price=280.0, best_bid=275.0, best_ask=285.0),
        p92000.symbol: Ticker(symbol=p92000.symbol, instrument_id=p92000.instrument_id, mark_price=102.0, best_bid=101.5, best_ask=102.5),
    }

    return adapter


@pytest.fixture
def test_settings(tmp_path):
    return Settings(
        _env_file=None,
        delta_env=Environment.TESTNET,
        delta_testnet_api_key="mock_testnet_key",
        delta_testnet_api_secret="mock_testnet_secret",
        data_dir=str(tmp_path / "data"),
        logs_dir=str(tmp_path / "logs"),
        state_file=str(tmp_path / "data" / "trade_state_test.json"),
        order_quantity=1.0,
        target_premium=100.0,
        premium_tolerance_usd=30.0,
        sl_percentage=1.0,
    )
