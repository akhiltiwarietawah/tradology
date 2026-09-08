"""Delta Exchange India Schema Mapper converting API dictionaries to generic models."""

from typing import Dict, Any, Optional
from datetime import datetime
import pytz

from src.core.models.instrument import Instrument, InstrumentType, OptionType
from src.core.models.order import Order, OrderSide, OrderType, OrderState, TimeInForce, Fill
from src.core.models.position import Position
from src.core.models.market_data import Ticker


class DeltaMapper:
    """Utility class translating Delta Exchange India data formats to generic engine models."""

    @staticmethod
    def to_instrument(data: Dict[str, Any]) -> Instrument:
        contract_type_raw = str(data.get("contract_type", "")).lower()

        if "call_options" in contract_type_raw:
            inst_type = InstrumentType.OPTION
            opt_type = OptionType.CALL
        elif "put_options" in contract_type_raw:
            inst_type = InstrumentType.OPTION
            opt_type = OptionType.PUT
        elif "perpetual" in contract_type_raw:
            inst_type = InstrumentType.PERPETUAL
            opt_type = None
        elif "future" in contract_type_raw:
            inst_type = InstrumentType.FUTURES
            opt_type = None
        else:
            inst_type = InstrumentType.SPOT
            opt_type = None

        strike = data.get("strike_price")
        strike_val = float(strike) if strike is not None and strike != "" else None

        # Expiry timestamp
        expiry_dt = None
        settle_time = data.get("settlement_time")
        if settle_time is not None:
            if isinstance(settle_time, (int, float)):
                ts = settle_time / 1e6 if settle_time > 1e11 else (settle_time / 1e3 if settle_time > 1e10 else settle_time)
                try:
                    expiry_dt = datetime.fromtimestamp(ts, tz=pytz.UTC)
                except Exception:
                    pass
            elif isinstance(settle_time, str):
                if settle_time.isdigit():
                    val = float(settle_time)
                    ts = val / 1e6 if val > 1e11 else (val / 1e3 if val > 1e10 else val)
                    try:
                        expiry_dt = datetime.fromtimestamp(ts, tz=pytz.UTC)
                    except Exception:
                        pass
                else:
                    try:
                        clean_str = settle_time.replace("Z", "+00:00")
                        expiry_dt = datetime.fromisoformat(clean_str)
                    except Exception:
                        pass

        # Fallback to symbol date parsing if settlement_time wasn't resolved: [C/P]-[UNDERLYING]-[STRIKE]-[DDMMYY]
        if not expiry_dt:
            sym = str(data.get("symbol", ""))
            parts = sym.split("-")
            if len(parts) >= 4 and len(parts[3]) == 6:
                try:
                    parsed_d = datetime.strptime(parts[3], "%d%m%y")
                    expiry_dt = parsed_d.replace(tzinfo=pytz.UTC)
                except Exception:
                    pass

        underlying = data.get("underlying_asset")
        underlying_symbol = underlying.get("symbol", "BTC") if isinstance(underlying, dict) else str(underlying or "BTC")

        return Instrument(
            exchange="delta",
            instrument_id=str(data["id"]),
            symbol=str(data["symbol"]),
            underlying=underlying_symbol,
            instrument_type=inst_type,
            option_type=opt_type,
            strike_price=strike_val,
            expiry=expiry_dt,
            contract_value=float(data.get("contract_value", 0.001) or 0.001),
            tick_size=float(data.get("tick_size", 0.1) or 0.1),
            min_order_size=float(data.get("min_order_size", 1.0) or 1.0),
            quoting_asset=str(data.get("quoting_asset", {}).get("symbol", "USD") if isinstance(data.get("quoting_asset"), dict) else data.get("quoting_asset", "USD")),
            settling_asset=str(data.get("settling_asset", {}).get("symbol", "USDT") if isinstance(data.get("settling_asset"), dict) else data.get("settling_asset", "USDT")),
            is_active=(str(data.get("state", "live")).lower() == "live"),
            raw_data=data,
        )

    @staticmethod
    def to_ticker(data: Dict[str, Any]) -> Ticker:
        quotes = data.get("quotes", {}) or {}
        best_bid = float(
            quotes.get("best_bid")
            or quotes.get("bid")
            or data.get("best_bid")
            or data.get("bid")
            or 0.0
        )
        best_ask = float(
            quotes.get("best_ask")
            or quotes.get("ask")
            or data.get("best_ask")
            or data.get("ask")
            or 0.0
        )

        mark_price = float(data.get("mark_price", 0.0) or 0.0)
        spot_price = float(data.get("spot_price", 0.0) or data.get("index_price", 0.0) or 0.0)
        last_price = float(data.get("close", 0.0) or data.get("last_price", 0.0) or mark_price)

        return Ticker(
            symbol=str(data.get("symbol", "")),
            instrument_id=str(data.get("product_id") or data.get("id") or ""),
            mark_price=mark_price,
            spot_price=spot_price,
            best_bid=best_bid,
            best_ask=best_ask,
            last_price=last_price,
            volume_24h=float(data.get("volume", 0.0) or 0.0),
            timestamp=data.get("timestamp"),
            raw_data=data,
        )

    @staticmethod
    def to_order(data: Dict[str, Any]) -> Order:
        state_raw = str(data.get("state", "open")).lower()
        if state_raw in ("filled", "closed"):
            state = OrderState.FILLED
        elif state_raw in ("cancelled", "canceled"):
            state = OrderState.CANCELLED
        elif state_raw in ("rejected",):
            state = OrderState.REJECTED
        elif state_raw in ("partially_filled", "partial_fill"):
            state = OrderState.PARTIALLY_FILLED
        elif state_raw in ("pending", "untriggered"):
            state = OrderState.PENDING
        else:
            state = OrderState.OPEN

        side_raw = str(data.get("side", "buy")).lower()
        side = OrderSide.BUY if side_raw == "buy" else OrderSide.SELL

        type_raw = str(data.get("order_type", "market_order")).lower()
        order_type = OrderType.LIMIT if "limit" in type_raw else OrderType.MARKET

        order_id = data.get("id")
        return Order(
            order_id=str(order_id) if order_id is not None else None,
            client_order_id=data.get("client_order_id"),
            instrument_id=str(data.get("product_id", "")),
            symbol=str(data.get("symbol", "")),
            side=side,
            order_type=order_type,
            quantity=float(data.get("size", 0.0)),
            price=float(data["limit_price"]) if data.get("limit_price") is not None else None,
            stop_price=float(data["stop_price"]) if data.get("stop_price") is not None else None,
            state=state,
            filled_quantity=float(data.get("filled_size", 0.0) or 0.0),
            unfilled_quantity=float(data.get("unfilled_size", 0.0) or 0.0),
            average_fill_price=float(data["average_fill_price"]) if data.get("average_fill_price") is not None else None,
            reduce_only=bool(data.get("reduce_only", False)),
            time_in_force=TimeInForce.GTC,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            raw_data=data,
        )

    @staticmethod
    def to_position(data: Dict[str, Any]) -> Position:
        return Position(
            instrument_id=str(data.get("product_id", "")),
            symbol=str(data.get("symbol", "")),
            size=float(data.get("size", 0.0)),
            entry_price=float(data.get("entry_price", 0.0) or 0.0),
            realized_pnl=float(data.get("realized_pnl", 0.0) or 0.0),
            unrealized_pnl=float(data.get("unrealized_pnl", 0.0) or 0.0),
            liquidation_price=float(data["liquidation_price"]) if data.get("liquidation_price") is not None else None,
            raw_data=data,
        )

    @staticmethod
    def to_fill(data: Dict[str, Any]) -> Fill:
        side_raw = str(data.get("side", "buy")).lower()
        side = OrderSide.BUY if side_raw == "buy" else OrderSide.SELL

        return Fill(
            fill_id=str(data.get("id", "")),
            order_id=str(data.get("order_id", "")),
            client_order_id=data.get("client_order_id"),
            instrument_id=str(data.get("product_id", "")),
            symbol=str(data.get("symbol", "")),
            side=side,
            quantity=float(data.get("size", 0.0)),
            price=float(data.get("price", 0.0)),
            fee=float(data.get("fee", 0.0) or 0.0),
            fee_asset=str(data.get("fee_asset", "USDT")),
            timestamp=data.get("created_at"),
            raw_data=data,
        )

    @staticmethod
    def to_account_balance(raw_balances: Any) -> Any:
        from src.core.models.account import AssetBalance, AccountBalance
        balance_list = raw_balances if isinstance(raw_balances, list) else (raw_balances.get("result", []) if isinstance(raw_balances, dict) else [])
        balances = {}
        for item in balance_list:
            asset = item.get("asset_symbol", "")
            if not asset:
                continue
            bal = float(item.get("balance") or 0.0)
            avail = float(item.get("available_balance") or 0.0)
            blocked = float(item.get("blocked_margin") or 0.0)
            bal_inr = float(item.get("balance_inr")) if item.get("balance_inr") is not None else None
            avail_inr = float(item.get("available_balance_inr")) if item.get("available_balance_inr") is not None else None
            balances[asset] = AssetBalance(
                asset_symbol=asset,
                balance=bal,
                available_balance=avail,
                blocked_margin=blocked,
                balance_inr=bal_inr,
                available_balance_inr=avail_inr,
            )
        return AccountBalance(balances=balances)
