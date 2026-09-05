"""Trading Engine constants and Delta Exchange India defaults."""

import pytz

# Timezones
IST_TIMEZONE = pytz.timezone("Asia/Kolkata")
UTC_TIMEZONE = pytz.UTC

# Delta Exchange India Endpoints
TESTNET_REST_URL = "https://cdn-ind.testnet.deltaex.org"
TESTNET_WS_URL = "wss://socket-ind.testnet.deltaex.org"
TESTNET_WS_PUB_URL = "wss://socket-ind-pub.testnet.deltaex.org"

LIVE_REST_URL = "https://api.india.delta.exchange"
LIVE_WS_URL = "wss://socket.india.delta.exchange"
LIVE_WS_PUB_URL = "wss://public-socket.india.delta.exchange"

# REST API Paths
PATH_PRODUCTS = "/v2/products"
PATH_TICKERS = "/v2/tickers"
PATH_TICKERS_BATCH = "/v2/tickers/batch"
PATH_INDICES = "/v2/indices"
PATH_ORDERS = "/v2/orders"
PATH_ORDERS_BATCH = "/v2/orders/batch"
PATH_ORDERS_HISTORY = "/v2/orders/history"
PATH_ORDERS_BRACKET = "/v2/orders/bracket"
PATH_POSITIONS = "/v2/positions"
PATH_POSITIONS_MARGINED = "/v2/positions/margined"
PATH_FILLS = "/v2/fills"
PATH_WALLET_BALANCES = "/v2/wallet/balances"

# WebSocket Channels
WS_CHANNEL_TICKER = "v2/ticker"
WS_CHANNEL_ALL_TICKERS = "all_tickers"
WS_CHANNEL_ORDERS = "orders"
WS_CHANNEL_POSITIONS = "positions"
WS_CHANNEL_HEARTBEATS = "heartbeats"
# Technical Specifications
BTC_CONTRACT_VALUE = 0.001  # 1 contract = 0.001 BTC on Delta Exchange India
