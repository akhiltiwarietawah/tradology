"""Renko Ichimoku asset catalog (beyond legacy ETH/SOL/XRP env flags)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RenkoAssetSpec:
    instance_id: str
    strategy_code: str
    default_symbol: str
    default_box_usd: float
    display_asset: str


DEFAULT_RENKO_SIZING_BASE_USD = 50.0

# Soft guidance when multiple Renko instances share one Delta wallet (margin overlap).
RENKO_SOFT_MAX_PER_WALLET = 4


def strategy_code_for(instance_id: str) -> str:
    return f"renko_ichimoku_{instance_id.lower()}"


# Legacy + registry — used for docs, migrations, and UI catalog.
RENKO_CORE_INSTANCE_IDS = ("eth", "sol", "xrp")


# Default 0.5% median boxes from btc-backtest (Sep 2026). Override per asset via env
# RENKO_ICHIMOKU_<ID>_BOX_SIZE (e.g. RENKO_ICHIMOKU_BTC_BOX_SIZE).
RENKO_ALT_REGISTRY: dict[str, RenkoAssetSpec] = {
    "btc": RenkoAssetSpec("btc", strategy_code_for("btc"), "BTCUSDT", 218.0, "BTC"),
    "bnb": RenkoAssetSpec("bnb", strategy_code_for("bnb"), "BNBUSDT", 1.87, "BNB"),
    "doge": RenkoAssetSpec("doge", strategy_code_for("doge"), "DOGEUSDT", 0.0005, "DOGE"),
    "ada": RenkoAssetSpec("ada", strategy_code_for("ada"), "ADAUSDT", 0.0021, "ADA"),
    "trx": RenkoAssetSpec("trx", strategy_code_for("trx"), "TRXUSDT", 0.0004, "TRX"),
    "avax": RenkoAssetSpec("avax", strategy_code_for("avax"), "AVAXUSDT", 0.102, "AVAX"),
    "link": RenkoAssetSpec("link", strategy_code_for("link"), "LINKUSDT", 0.063, "LINK"),
    # Enable only if Delta lists the perp; symbol may need adjustment per exchange.
    "hype": RenkoAssetSpec("hype", strategy_code_for("hype"), "HYPEUSDT", 0.21, "HYPE"),
}


def parse_enabled_alt_ids(raw: str) -> list[str]:
    if not raw or not str(raw).strip():
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in str(raw).replace(";", ",").split(","):
        key = part.strip().lower()
        if not key or key in seen:
            continue
        if key not in RENKO_ALT_REGISTRY:
            continue
        seen.add(key)
        out.append(key)
    return out
