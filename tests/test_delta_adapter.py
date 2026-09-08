"""Tests for Delta Exchange India REST client, mapper, and adapter."""

import pytest
from unittest.mock import AsyncMock, patch
from src.exchanges.delta.mapper import DeltaMapper
from src.exchanges.delta.client import DeltaRestClient, DeltaTimeoutError
from src.core.models.instrument import InstrumentType, OptionType
from src.core.models.order import OrderState, OrderSide


def test_delta_mapper_to_instrument():
    raw_prod = {
        "id": 12345,
        "symbol": "C-BTC-95000-010926",
        "contract_type": "call_options",
        "strike_price": "95000",
        "contract_value": "0.001",
        "tick_size": "0.1",
        "min_order_size": "1",
        "state": "live",
        "underlying_asset": {"symbol": "BTC"},
    }
    inst = DeltaMapper.to_instrument(raw_prod)
    assert inst.instrument_id == "12345"
    assert inst.symbol == "C-BTC-95000-010926"
    assert inst.instrument_type == InstrumentType.OPTION
    assert inst.option_type == OptionType.CALL
    assert inst.strike_price == 95000.0
    assert inst.contract_value == 0.001
    assert inst.is_active is True


def test_delta_mapper_to_order():
    raw_order = {
        "id": 998877,
        "client_order_id": "STR_123_CE_ent_s_456",
        "product_id": 12345,
        "symbol": "C-BTC-95000-010926",
        "side": "sell",
        "order_type": "market_order",
        "size": "0.01",
        "state": "filled",
        "filled_size": "0.01",
        "average_fill_price": "99.5",
    }
    order = DeltaMapper.to_order(raw_order)
    assert order.order_id == "998877"
    assert order.client_order_id == "STR_123_CE_ent_s_456"
    assert order.side == OrderSide.SELL
    assert order.state == OrderState.FILLED
    assert order.average_fill_price == 99.5


def test_delta_signature_generation():
    client = DeltaRestClient(
        base_url="https://cdn-ind.testnet.deltaex.org",
        api_key="test_key",
        api_secret="test_secret",
    )
    sig = client._generate_signature("GET", "/v2/positions", "", "", "1700000000")
    assert isinstance(sig, str)
    assert len(sig) == 64  # SHA256 hex string length


@pytest.mark.asyncio
async def test_place_order_timeout_recovery():
    client = DeltaRestClient(
        base_url="https://cdn-ind.testnet.deltaex.org",
        api_key="test_key",
        api_secret="test_secret",
    )

    # Mock request to raise timeout on POST /v2/orders, but return order on get_order_by_client_id
    with patch.object(client, "request", side_effect=DeltaTimeoutError("Network timeout")):
        with patch.object(
            client,
            "get_order_by_client_id",
            return_value={"id": 8888, "client_order_id": "test_cid", "state": "filled", "product_id": 101, "size": 1, "side": "sell"},
        ):
            res = await client.place_order(product_id=101, size=1, side="sell", client_order_id="test_cid")
            assert res.get("id") == 8888
            assert res.get("state") == "filled"


@pytest.mark.asyncio
async def test_delta_ws_message_handling():
    from src.exchanges.delta.ws_client import DeltaWsClient
    import json

    client = DeltaWsClient(
        ws_url="wss://socket.india.delta.exchange",
        api_key="k",
        api_secret="s",
    )

    received_tickers = []
    async def _on_tick(data):
        received_tickers.append(data)

    client.add_ticker_callback(_on_tick)

    # 1. Simulate subscriptions confirmation
    sub_msg = json.dumps({"type": "subscriptions", "channels": [{"name": "v2/ticker", "symbols": ["BTCUSD"]}]})
    await client._handle_message(sub_msg)

    # 2. Simulate incoming live ticker message
    raw_tick = json.dumps({
        "type": "v2/ticker",
        "symbol": "C-BTC-95000-010926",
        "mark_price": "105.50",
        "quotes": {"best_bid": "104.0", "best_ask": "107.0"},
    })
    await client._handle_message(raw_tick)
    import asyncio
    await asyncio.sleep(0.01)

    assert len(received_tickers) == 1
    assert received_tickers[0]["symbol"] == "C-BTC-95000-010926"
    assert received_tickers[0]["mark_price"] == "105.50"
    cached = client.get_latest_ticker("C-BTC-95000-010926")
    assert cached is not None
    assert cached["mark_price"] == "105.50"


def test_delta_ws_stale_detection():
    from src.exchanges.delta.ws_client import DeltaWsClient
    import time

    client = DeltaWsClient(
        ws_url="wss://socket.india.delta.exchange",
        api_key="k",
        api_secret="s",
        stale_threshold_seconds=5.0,
    )
    client._connected = True
    client._ws = type("MockWS", (), {"closed": False, "close_code": None, "state": "OPEN"})()

    # If no symbols are subscribed, it should not be considered stale
    assert client.is_stale is False

    # Subscribe to a symbol
    client._subscribed_symbols.add("BTCUSD")
    client._last_msg_timestamp = time.time()
    assert client.is_stale is False

    # Set last message timestamp back in time (>5s ago)
    client._last_msg_timestamp = time.time() - 10.0
    assert client.is_stale is True


def test_delta_mapper_to_account_balance():
    raw = [
        {
            "asset_symbol": "USD",
            "balance": "50.0",
            "available_balance": "40.0",
            "blocked_margin": "10.0",
            "balance_inr": "4325.0",
            "available_balance_inr": "3460.0",
        },
        {
            "asset_symbol": "INR",
            "balance": "2500.0",
            "available_balance": "2500.0",
            "blocked_margin": "0.0",
        },
    ]
    acc_bal = DeltaMapper.to_account_balance(raw)
    assert "USD" in acc_bal.balances
    assert "INR" in acc_bal.balances
    usd = acc_bal.balances["USD"]
    assert usd.balance == 50.0
    assert usd.available_balance == 40.0
    assert usd.blocked_margin == 10.0
    assert usd.balance_inr == 4325.0
    inr = acc_bal.balances["INR"]
    assert inr.balance == 2500.0
    assert inr.available_balance == 2500.0


@pytest.mark.asyncio
async def test_delta_adapter_create_bracket_order_success(mocker):
    """Verify create_bracket_order sends correct POST /v2/orders/bracket payload."""
    from src.exchanges.delta.adapter import DeltaExchangeAdapter
    from src.exchanges.delta.client import DeltaRestClient

    mock_client = mocker.AsyncMock(spec=DeltaRestClient)
    mock_client.create_bracket_order.return_value = {
        "id": 1510213564,
        "product_id": 150403,
        "stop_price": "200.0",
        "state": "pending",
    }

    adapter = DeltaExchangeAdapter(rest_url="https://api.example.com", ws_url="wss://ws.example.com")
    adapter.rest_client = mock_client
    res = await adapter.create_bracket_order(
        instrument_id="150403",
        stop_loss_price=200.0,
        stop_trigger_method="mark_price",
    )

    assert res["id"] == 1510213564
    mock_client.create_bracket_order.assert_called_once_with(
        product_id=150403,
        stop_loss_price=200.0,
        take_profit_price=None,
        stop_trigger_method="mark_price",
        order_type="market_order",
    )


@pytest.mark.asyncio
async def test_delta_adapter_create_bracket_order_with_take_profit(mocker):
    """Verify adapter passes both stop_loss_price and take_profit_price to REST client."""
    from src.exchanges.delta.adapter import DeltaExchangeAdapter
    from src.exchanges.delta.client import DeltaRestClient

    mock_client = mocker.AsyncMock(spec=DeltaRestClient)
    mock_client.create_bracket_order.return_value = {
        "id": 1510213565,
        "product_id": 150403,
        "stop_price": "200.0",
        "take_profit_price": "2.0",
    }

    adapter = DeltaExchangeAdapter(rest_url="https://api.example.com", ws_url="wss://ws.example.com")
    adapter.rest_client = mock_client
    res = await adapter.create_bracket_order(
        instrument_id="150403",
        stop_loss_price=200.0,
        take_profit_price=2.0,
        stop_trigger_method="mark_price",
    )

    assert res["id"] == 1510213565
    mock_client.create_bracket_order.assert_called_once_with(
        product_id=150403,
        stop_loss_price=200.0,
        take_profit_price=2.0,
        stop_trigger_method="mark_price",
        order_type="market_order",
    )


@pytest.mark.asyncio
async def test_delta_adapter_create_bracket_order_idempotency_on_bracket_exists(mocker):
    """Verify idempotency: if bracket already exists on Delta, adapter queries and returns existing bracket."""
    from src.exchanges.delta.adapter import DeltaExchangeAdapter
    from src.exchanges.delta.client import DeltaRestClient, DeltaAPIError

    mock_client = mocker.AsyncMock(spec=DeltaRestClient)
    mock_client.create_bracket_order.side_effect = DeltaAPIError("Delta API HTTP 400: bracket_order_exists")
    mock_client.get_open_orders.return_value = [
        {
            "id": 999111,
            "product_id": 150403,
            "bracket_order": True,
            "stop_order_type": "stop_loss_order",
            "stop_price": "200.0",
        }
    ]

    adapter = DeltaExchangeAdapter(rest_url="https://api.example.com", ws_url="wss://ws.example.com")
    adapter.rest_client = mock_client
    res = await adapter.create_bracket_order(
        instrument_id="150403",
        stop_loss_price=200.0,
    )

    assert res["id"] == 999111
    assert res["bracket_order"] is True


@pytest.mark.asyncio
async def test_delta_client_market_order_payload_schema(mocker):
    """Verify market order payload has integer size, omits time_in_force, and includes expected fields."""
    client = DeltaRestClient(
        base_url="https://cdn-ind.testnet.deltaex.org",
        api_key="test_key",
        api_secret="test_secret",
    )

    mock_request = mocker.patch.object(client, "request", return_value={"result": {"id": 12345, "state": "open"}})

    res = await client.place_order(
        product_id=150246,
        size=10,
        side="sell",
        order_type="market_order",
        client_order_id="S_260902_090000_CE_ent_s_2743",
    )

    assert res["id"] == 12345
    mock_request.assert_called_once()
    args, kwargs = mock_request.call_args
    assert args[0] == "POST"
    assert args[1] == "/v2/orders"

    payload = kwargs["data"]
    assert payload == {
        "product_id": 150246,
        "size": 10,
        "side": "sell",
        "order_type": "market_order",
        "client_order_id": "S_260902_090000_CE_ent_s_2743",
    }
    # Verify strict data types
    assert isinstance(payload["size"], int)
    assert not isinstance(payload["size"], float)
    assert len(payload["client_order_id"]) <= 32
    assert "time_in_force" not in payload
    assert "limit_price" not in payload


@pytest.mark.asyncio
async def test_delta_client_limit_order_payload_schema(mocker):
    """Verify limit order payload has integer size, includes time_in_force, and serializes limit_price."""
    client = DeltaRestClient(
        base_url="https://cdn-ind.testnet.deltaex.org",
        api_key="test_key",
        api_secret="test_secret",
    )

    mock_request = mocker.patch.object(client, "request", return_value={"result": {"id": 67890, "state": "open"}})

    res = await client.place_order(
        product_id=150234,
        size=10.0,
        side="buy",
        order_type="limit_order",
        limit_price=117.5,
        time_in_force="gtc",
        client_order_id="TEST_LIMIT_1",
    )

    assert res["id"] == 67890
    mock_request.assert_called_once()
    _, kwargs = mock_request.call_args
    payload = kwargs["data"]

    assert payload == {
        "product_id": 150234,
        "size": 10,
        "side": "buy",
        "order_type": "limit_order",
        "time_in_force": "gtc",
        "limit_price": "117.5",
        "client_order_id": "TEST_LIMIT_1",
    }
    assert isinstance(payload["size"], int)
    assert payload["time_in_force"] == "gtc"
    assert payload["limit_price"] == "117.5"
    assert len(payload["client_order_id"]) <= 32


@pytest.mark.asyncio
async def test_delta_client_size_validation():
    """Verify DeltaRestClient rejects fractional or non-positive contract quantities locally."""
    client = DeltaRestClient(
        base_url="https://cdn-ind.testnet.deltaex.org",
        api_key="test_key",
        api_secret="test_secret",
    )

    # Fractional contract quantity (e.g. 10.5) must raise ValueError rather than silently rounding
    with pytest.raises(ValueError, match="must be a whole number of contracts"):
        await client.place_order(product_id=100, size=10.5, side="sell")

    with pytest.raises(ValueError, match="must be a whole number of contracts"):
        await client.place_order(product_id=100, size=0.01, side="buy")

    # Non-positive contract quantity must raise ValueError
    with pytest.raises(ValueError, match="must be positive"):
        await client.place_order(product_id=100, size=0, side="sell")

    with pytest.raises(ValueError, match="must be positive"):
        await client.place_order(product_id=100, size=-5, side="buy")


@pytest.mark.asyncio
async def test_get_recent_fills_for_product_uses_product_ids_not_side_query():
    """Delta /v2/fills requires product_ids (plural) and has no side query param."""
    client = DeltaRestClient(
        base_url="https://api.india.delta.exchange",
        api_key="test_key",
        api_secret="test_secret",
    )
    captured = {}

    async def fake_request(method, path, params=None, data=None, auth_required=True):
        captured["method"] = method
        captured["path"] = path
        captured["params"] = params
        return {
            "result": [
                {"side": "sell", "price": "89", "size": "5", "commission": "0.01"},
                {"side": "buy", "price": "194", "size": "5", "commission": "0.04"},
            ]
        }

    client.request = fake_request  # type: ignore
    buys = await client.get_recent_fills_for_product(
        product_id=150988,
        side="buy",
        page_size=50,
        start_time_us=1757130000000000,
    )
    assert captured["path"] == "/v2/fills"
    assert captured["params"]["product_ids"] == "150988"
    assert "product_id" not in captured["params"]
    assert "side" not in captured["params"]
    assert captured["params"]["start_time"] == "1757130000000000"
    assert len(buys) == 1
    assert buys[0]["price"] == "194"


