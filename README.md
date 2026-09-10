# Tradology BTC 0DTE Options Trading Engine (Delta Exchange India)

A modular, production-grade Python algorithmic trading engine architected for multi-exchange and multi-strategy extensibility and automated derivatives trading.

The initial strategy implementation executes same-day expiry (0DTE) short strangles on Bitcoin (BTC) for **Delta Exchange India** forward testing.

---

## Key Features

* **Multi-Exchange Extensibility**: Generic abstractions (`BaseExchangeAdapter`, `Instrument`, `Order`, `Position`, `Ticker`) decouple strategies from venue-specific APIs.
* **Multi-Strategy Extensibility**: Strategies implement `BaseStrategy` with standardized lifecycles and event hooks.
* **Single `.env` Configuration**: Unified environment file supporting both Testnet and Live configurations with seamless switching via `DELTA_ENV=testnet` or `DELTA_ENV=live`.
* **Safe Defaults**: Strictly defaults to `DELTA_ENV=testnet`. Live trading requires explicit configuration and non-empty credentials.
* **Two-Leg Entry Failure Policy**: If Leg 1 fills and Leg 2 fails/times out, the engine verifies Leg 2 on the exchange and immediately flattens Leg 1 to prevent unintended naked short exposure.
* **Manual Trade Isolation**: Unrelated manual positions (e.g. BTC perpetuals, ETH options) on the account are detected and left untouched. If a strategy leg is manually closed, the engine marks the leg as `MANUALLY_CLOSED` and continues managing the remaining leg.
* **Independent 100% Stop Loss**: Each short leg has its own 100% premium stop loss (2x entry price). When one leg triggers SL, it is closed while the other leg continues running.
* **Time-Based IST Rules**: Automatic strike discovery & entry at 09:00 IST and forced square-off at 17:15 IST.
* **Restart Recovery**: Atomic state persistence (`data/trade_state.json`) and exchange reconciliation upon server restart.
* **FastAPI Monitoring & Control**: Built-in REST API for health checks, live position inspection, manual reconciliation, and emergency kill switch.
* **Comprehensive Structured Logging**: Formatted console logging + JSONL trade event ledger (`logs/trades.jsonl`).

---

## Directory Structure

```
btc-strangle-bot/
├── src/
│   ├── config/               # Settings & constants (Single .env management)
│   │   ├── constants.py
│   │   └── settings.py
│   ├── core/                 # Generic domain models, events & interfaces
│   │   ├── models/           # Instrument, Order, Position, Ticker, Trade
│   │   ├── events/           # Async typed EventBus
│   │   ├── interfaces/       # BaseExchangeAdapter, IStrategy, IExecutionEngine
│   │   └── scheduler/        # IST 09:00 / 17:15 strategy scheduler
│   ├── exchanges/            # Multi-exchange layer
│   │   ├── base/             # BaseExchangeAdapter ABC
│   │   ├── delta/            # Delta India REST client, WS client & mapper
│   │   └── service.py        # ExchangeService registry
│   ├── strategies/           # Strategy layer
│   │   ├── base/             # BaseStrategy abstract class
│   │   └── short_strangle/   # BTC 0DTE Short Strangle implementation
│   ├── execution/            # Order manager & execution engine
│   ├── risk/                 # Risk manager, max daily loss & kill switch
│   ├── reconciliation/       # State reconciliation & manual trade isolation
│   ├── state/                # In-memory store & atomic disk persistence
│   ├── logging_utils/        # Formatted console & structured JSONL loggers
│   └── api/                  # FastAPI app & REST control routes
├── main.py                   # Main CLI & server entrypoint
├── requirements.txt          # Production & test dependencies
├── .env.example              # Configuration template
├── .env                      # Active configuration
├── .gitignore
├── README.md
└── tests/                    # Comprehensive unit & integration test suite
```

---

## Environment Configuration

The engine uses **one single `.env` file** for both Testnet and Live environments:

```bash
# ----------------------------------------------------
# Select Environment: 'testnet' or 'live' (DEFAULT: testnet)
# ----------------------------------------------------
DELTA_ENV=testnet

# Testnet Credentials & Endpoints (Delta Exchange India Testnet)
DELTA_TESTNET_API_KEY=your_testnet_api_key
DELTA_TESTNET_API_SECRET=your_testnet_api_secret
DELTA_TESTNET_REST_URL=https://cdn-ind.testnet.deltaex.org
DELTA_TESTNET_WS_URL=wss://socket-ind.testnet.deltaex.org

# Live Credentials & Endpoints (Delta Exchange India Live)
DELTA_LIVE_API_KEY=
DELTA_LIVE_API_SECRET=
DELTA_LIVE_REST_URL=https://api.india.delta.exchange
DELTA_LIVE_WS_URL=wss://socket.india.delta.exchange

# Strategy Settings
STRATEGY=short_strangle
UNDERLYING=BTC
TARGET_PREMIUM=100.0
PREMIUM_TOLERANCE_USD=30.0
ORDER_QUANTITY=0.01
SL_PERCENTAGE=1.0
ENTRY_TIME_IST=09:00:00
EXIT_TIME_IST=17:15:00
MAX_DAILY_LOSS_USD=500.0
KILL_SWITCH=false
DRY_RUN=false
```

### Switching Environments
* **To run TESTNET**: Ensure `DELTA_ENV=testnet` in `.env`.
* **To switch to LIVE**: Set `DELTA_ENV=live` and provide `DELTA_LIVE_API_KEY` and `DELTA_LIVE_API_SECRET`. No Python code modifications are needed.

---

## How to Run

### 1. Install Dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Run in Forward-Testing Mode (CLI)
```bash
python3 main.py
```

### 3. Run with FastAPI Management Server
```bash
python3 main.py --api
```
Access the REST API at `http://localhost:8000/docs`.

### 4. Check Current Trade Status
```bash
python3 main.py --status
```

### 5. Run One-Shot Reconciliation
```bash
python3 main.py --reconcile-only
```

---

## REST API Endpoints

* `GET /api/v1/status`: Engine health, connected exchanges, kill-switch status, and current trade snapshot.
* `GET /api/v1/trades`: Active trade details and historical trade records.
* `POST /api/v1/reconcile`: Manually trigger exchange state reconciliation.
* `POST /api/v1/kill-switch`: Programmatically engage the emergency kill switch.

---

## PostgreSQL Database Management

PostgreSQL is used exclusively for historical persistence and analytics. Trading safety and crash recovery operate independently.

### Start Database
```bash
docker compose up -d postgres
```

### Check Database Health & Status
```bash
docker compose ps
```

### View Database Logs
```bash
docker compose logs -f postgres
```

### Inspect Database CLI (psql)
```bash
docker compose exec postgres psql -U postgres -d crypto_trading
```

### Stop Database
```bash
docker compose down
```

### Reset Database (Development)
```bash
docker compose down -v
docker compose up -d postgres
```

---

## Independent ETHUSDT Renko + Ichimoku

A second strategy can run in the same process without changing short-strangle logic. See **[docs/RENKO_ICHIMOKU.md](docs/RENKO_ICHIMOKU.md)** for switches, accounts, and position size.

Defaults keep production behavior: `EXISTING_STRATEGY_ENABLED=true`, `RENKO_ICHIMOKU_STRATEGY_ENABLED=false`.

---

## Running the Test Suite

```bash
pytest -v
```

