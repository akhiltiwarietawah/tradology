"""Delta Exchange India Adapter implementing BaseExchangeAdapter."""

import logging
import time
from typing import Dict, List, Optional, Any, Callable, Awaitable
from datetime import date

from src.core.interfaces.exchange import BaseExchangeAdapter
from src.core.models.instrument import Instrument, OptionChain, InstrumentType, OptionType
from src.core.models.order import Order, OrderRequest, OrderSide, OrderType
from src.core.models.position import Position
from src.core.models.market_data import Ticker
from src.exchanges.delta.client import DeltaRestClient, DeltaAPIError
from src.exchanges.delta.ws_client import DeltaWsClient
from src.exchanges.delta.mapper import DeltaMapper


class DeltaExchangeAdapter(BaseExchangeAdapter):
    """Adapter bridging Delta Exchange India REST and WebSocket APIs to generic engine abstractions."""

    def __init__(
        self,
        rest_url: str,
        ws_url: str,
        api_key: str = "",
        api_secret: str = "",
        is_testnet: bool = True,
        logger: Optional[logging.Logger] = None,
    ):
        self._exchange_name = "delta_india"
        self.is_testnet = is_testnet
        self.logger = logger or logging.getLogger("delta_adapter")
        self.rest_client = DeltaRestClient(
            base_url=rest_url,
            api_key=api_key,
            api_secret=api_secret,
            logger=self.logger,
        )
        self.ws_client = DeltaWsClient(
            ws_url=ws_url,
            api_key=api_key,
            api_secret=api_secret,
            logger=self.logger,
        )
        self._initialized = False

    @property
    def exchange_name(self) -> str:
        return self._exchange_name

    @property
    def is_connected(self) -> bool:
        return self.ws_client.is_connected

    @property
    def is_stale(self) -> bool:
        return self.ws_client.is_stale

    def is_ws_stale(self) -> bool:
        return self.ws_client.is_stale

    def get_latest_ticker(self, symbol_or_id: str) -> Optional[Ticker]:
        """Return last cached WS ticker for a symbol or product id, if any."""
        raw = self.ws_client.get_latest_ticker(symbol_or_id)
        if not raw:
            return None
        return DeltaMapper.to_ticker(raw)

    async def initialize(self) -> bool:
        """Initialize connections and test authentication."""
        self.logger.info(f"Initializing DeltaExchangeAdapter (Environment: {'TESTNET' if self.is_testnet else 'LIVE'})...")
        await self.ws_client.connect()
        # Baseline subscription to underlying BTCUSD ensures continuous live ticker feed
        await self.ws_client.subscribe_tickers(["BTCUSD"])
        self._initialized = True
        return True

    async def close(self) -> None:
        """Close REST session and WebSocket connection."""
        await self.ws_client.stop()
        await self.rest_client.close()
        self._initialized = False
        self.logger.info("DeltaExchangeAdapter closed.")

    async def get_spot_price(self, underlying: str = "BTC") -> float:
        return await self.rest_client.get_spot_price(underlying)

    async def get_instruments(
        self,
        underlying: Optional[str] = None,
        instrument_type: Optional[InstrumentType] = None,
    ) -> List[Instrument]:
        raw_products = await self.rest_client.get_products()
        instruments = [DeltaMapper.to_instrument(p) for p in raw_products]

        filtered = []
        for inst in instruments:
            if underlying and inst.underlying.upper() != underlying.upper():
                continue
            if instrument_type and inst.instrument_type != instrument_type:
                continue
            filtered.append(inst)

        return filtered

    async def get_option_chain(self, underlying: str, expiry_date: date) -> OptionChain:
        instruments = await self.get_instruments(underlying=underlying, instrument_type=InstrumentType.OPTION)
        calls = []
        puts = []

        for inst in instruments:
            if inst.expiry and inst.expiry.date() == expiry_date:
                if inst.is_call:
                    calls.append(inst)
                elif inst.is_put:
                    puts.append(inst)

        return OptionChain(
            exchange=self.exchange_name,
            underlying=underlying,
            expiry_date=expiry_date,
            calls=calls,
            puts=puts,
        )

    async def get_tickers(self, symbols_or_ids: Optional[List[str]] = None) -> Dict[str, Ticker]:
        product_ids = []
        if symbols_or_ids:
            for s in symbols_or_ids:
                if str(s).isdigit():
                    product_ids.append(int(s))

        raw_tickers = await self.rest_client.get_tickers(product_ids=product_ids if product_ids else None)
        tickers_map = {}
        for raw in raw_tickers:
            ticker = DeltaMapper.to_ticker(raw)
            tickers_map[ticker.symbol] = ticker
            if ticker.instrument_id:
                tickers_map[ticker.instrument_id] = ticker
        return tickers_map

    async def get_positions(self) -> List[Position]:
        raw_positions = await self.rest_client.get_positions()
        return [DeltaMapper.to_position(p) for p in raw_positions]

    async def get_open_orders(self, instrument_id: Optional[str] = None) -> List[Order]:
        p_id = int(instrument_id) if instrument_id and instrument_id.isdigit() else None
        raw_orders = await self.rest_client.get_open_orders(product_id=p_id)
        return [DeltaMapper.to_order(o) for o in raw_orders]

    async def get_order_by_client_id(self, client_order_id: str) -> Optional[Order]:
        raw = await self.rest_client.get_order_by_client_id(client_order_id)
        return DeltaMapper.to_order(raw) if raw else None

    async def get_recent_fills_for_product(
        self,
        instrument_id: str,
        side: Optional[str] = None,
        page_size: int = 10,
        start_time_us: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch recent fills for a specific product (strategy leg only, no manual bleed-over)."""
        product_id = int(instrument_id) if instrument_id and str(instrument_id).isdigit() else int(instrument_id)
        return await self.rest_client.get_recent_fills_for_product(
            product_id=product_id,
            side=side,
            page_size=page_size,
            start_time_us=start_time_us,
        )

    async def place_order(self, order_request: OrderRequest) -> Order:
        product_id = int(order_request.instrument_id)
        side = "buy" if order_request.side == OrderSide.BUY else "sell"
        order_type = "limit_order" if order_request.order_type == OrderType.LIMIT else "market_order"

        raw = await self.rest_client.place_order(
            product_id=product_id,
            size=order_request.quantity,
            side=side,
            order_type=order_type,
            limit_price=order_request.price,
            stop_price=order_request.stop_price,
            stop_order_type=order_request.stop_order_type,
            client_order_id=order_request.client_order_id,
            reduce_only=order_request.reduce_only,
            time_in_force=order_request.time_in_force.value,
        )
        order = DeltaMapper.to_order(raw)
        order.strategy_id = order_request.strategy_id
        order.leg_id = order_request.leg_id
        return order

    async def cancel_order(self, order_id: str, instrument_id: str) -> bool:
        return await self.rest_client.cancel_order(
            order_id=int(order_id),
            product_id=int(instrument_id),
        )

    async def cancel_all_orders(self, instrument_id: Optional[str] = None) -> bool:
        p_id = int(instrument_id) if instrument_id and instrument_id.isdigit() else None
        return await self.rest_client.cancel_all_orders(product_id=p_id)

    async def subscribe_market_data(self, symbols: List[str], callback: Callable[[Ticker], Awaitable[None]]) -> None:
        async def _wrapper(raw_data: Dict[str, Any]):
            ticker = DeltaMapper.to_ticker(raw_data)
            await callback(ticker)

        self.ws_client.add_ticker_callback(_wrapper)
        await self.ws_client.subscribe_tickers(symbols)

    async def subscribe_private_events(
        self,
        order_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        position_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> None:
        if order_callback:
            self.ws_client.add_order_callback(order_callback)
        if position_callback:
            self.ws_client.add_position_callback(position_callback)

    async def get_account_balances(self) -> Any:
        raw_balances = await self.rest_client.get_wallet_balances()
        return DeltaMapper.to_account_balance(raw_balances)

    async def create_bracket_order(
        self,
        instrument_id: str,
        stop_loss_price: float,
        take_profit_price: Optional[float] = None,
        stop_trigger_method: str = "mark_price",
        order_type: str = "market_order",
    ) -> Dict[str, Any]:
        """Create native bracket Stop Loss and optional Take Profit on Delta Exchange with idempotency handling."""
        product_id = int(instrument_id)
        try:
            res = await self.rest_client.create_bracket_order(
                product_id=product_id,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                stop_trigger_method=stop_trigger_method,
                order_type=order_type,
            )
            return res
        except DeltaAPIError as e:
            if "bracket_order_exists" in str(e):
                self.logger.info(f"Native bracket order already exists on Delta for product {product_id}. Retrieving open orders...")
                open_orders = await self.rest_client.get_open_orders(product_id=product_id)
                for o in open_orders:
                    if o.get("bracket_order") or o.get("stop_order_type") == "stop_loss_order":
                        return o
                return {"status": "exists", "product_id": product_id}
            raise e

    async def get_bracket_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Fetch bracket order details from Delta."""
        return await self.rest_client.get_bracket_order(order_id=int(order_id))

    async def get_candles(self, symbol: str, resolution: str, limit: int = 500) -> List[Dict[str, Any]]:
        """Return newest-first or oldest-first candles; callers sort by time."""
        end = int(time.time())
        step = {
            "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
            "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400,
        }.get(resolution, 900)
        start = end - int(limit) * step
        return await self.rest_client.get_candles(symbol=symbol, resolution=resolution, start=start, end=end)

    async def get_perpetual_product(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Resolve a perpetual by symbol. Tries requested symbol then common ETH aliases."""
        products = await self.rest_client.get_perpetual_products()
        wanted = [symbol.upper(), symbol.upper().replace("USDT", "USD"), symbol.upper().replace("USD", "USDT")]
        seen = []
        for w in wanted:
            if w not in seen:
                seen.append(w)
        exact = symbol.upper()
        for w in seen:
            for p in products:
                if str(p.get("symbol", "")).upper() != w:
                    continue
                ct = str(p.get("contract_type", "")).lower()
                if "perpetual" not in ct:
                    continue
                inst = DeltaMapper.to_instrument(p)
                if inst.instrument_type != InstrumentType.PERPETUAL:
                    continue
                return {
                    "id": p.get("id"),
                    "instrument_id": inst.instrument_id,
                    "symbol": inst.symbol,
                    "contract_type": p.get("contract_type"),
                    "instrument_type": inst.instrument_type.value,
                    "exact_symbol_match": w == exact,
                    "raw": p,
                }
        self.logger.warning(f"No perpetual product found for {symbol} (tried {seen})")
        return None
