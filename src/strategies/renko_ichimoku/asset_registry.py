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
    rollout_group: str  # A | B | C | ZEC


DEFAULT_RENKO_SIZING_BASE_USD = 50.0

# Soft guidance when multiple Renko instances share one Delta wallet (margin overlap).
RENKO_SOFT_MAX_PER_WALLET = 4


def strategy_code_for(instance_id: str) -> str:
    return f"renko_ichimoku_{instance_id.lower()}"


RENKO_CORE_INSTANCE_IDS = ("eth", "sol", "xrp")

# Group A — primary 11 (core 3 + these 8 alts). Env: RENKO_ICHIMOKU_ALTS_ENABLED
RENKO_GROUP_A_ALT_IDS: tuple[str, ...] = (
    "btc",
    "bnb",
    "doge",
    "ada",
    "trx",
    "avax",
    "link",
    "hype",
)

# Group B — extension 8. Env: RENKO_ICHIMOKU_ALTS_GROUP_B_ENABLED
RENKO_GROUP_B_ALT_IDS: tuple[str, ...] = (
    "sui",
    "inj",
    "near",
    "apt",
    "pepe",
    "wif",
    "ena",
    "jup",
)

# Group C — exploratory 13. Env: RENKO_ICHIMOKU_ALTS_GROUP_C_ENABLED
RENKO_GROUP_C_ALT_IDS: tuple[str, ...] = (
    "ton",
    "dot",
    "atom",
    "ltc",
    "bch",
    "uni",
    "aave",
    "pol",
    "sei",
    "tia",
    "op",
    "arb",
    "paxg",
)

# ZEC — backtested separately; not in A/B/C. Env: RENKO_ICHIMOKU_ZEC_ENABLED=true
RENKO_ZEC_ALT_IDS: tuple[str, ...] = ("zec",)


def _spec(
    instance_id: str,
    symbol: str,
    box: float,
    asset: str,
    group: str,
) -> RenkoAssetSpec:
    iid = instance_id.lower()
    return RenkoAssetSpec(
        iid,
        strategy_code_for(iid),
        symbol,
        box,
        asset,
        group,
    )


# Default 0.5% median boxes from btc-backtest Mode 3 (Sep 2026). Override via
# RENKO_ICHIMOKU_<ID>_BOX_SIZE.
RENKO_GROUP_A_REGISTRY: dict[str, RenkoAssetSpec] = {
    "btc": _spec("btc", "BTCUSDT", 218.0, "BTC", "A"),
    "bnb": _spec("bnb", "BNBUSDT", 1.87, "BNB", "A"),
    "doge": _spec("doge", "DOGEUSDT", 0.0005, "DOGE", "A"),
    "ada": _spec("ada", "ADAUSDT", 0.0021, "ADA", "A"),
    "trx": _spec("trx", "TRXUSDT", 0.0004, "TRX", "A"),
    "avax": _spec("avax", "AVAXUSDT", 0.102, "AVAX", "A"),
    "link": _spec("link", "LINKUSDT", 0.063, "LINK", "A"),
    "hype": _spec("hype", "HYPEUSDT", 0.21, "HYPE", "A"),
}

RENKO_GROUP_B_REGISTRY: dict[str, RenkoAssetSpec] = {
    "sui": _spec("sui", "SUIUSDT", 0.006, "SUI", "B"),
    "inj": _spec("inj", "INJUSDT", 0.04, "INJ", "B"),
    "near": _spec("near", "NEARUSDT", 0.0139, "NEAR", "B"),
    "apt": _spec("apt", "APTUSDT", 0.0299, "APT", "B"),
    "pepe": _spec("pepe", "PEPEUSDT", 0.0000005, "PEPE", "B"),
    "wif": _spec("wif", "WIFUSDT", 0.004, "WIF", "B"),
    "ena": _spec("ena", "ENAUSDT", 0.0017, "ENA", "B"),
    "jup": _spec("jup", "JUPUSDT", 0.0025, "JUP", "B"),
}

RENKO_GROUP_C_REGISTRY: dict[str, RenkoAssetSpec] = {
    "ton": _spec("ton", "TONUSDT", 0.0152, "TON", "C"),
    "dot": _spec("dot", "DOTUSDT", 0.0288, "DOT", "C"),
    "atom": _spec("atom", "ATOMUSDT", 0.0361, "ATOM", "C"),
    "ltc": _spec("ltc", "LTCUSDT", 0.3982, "LTC", "C"),
    "bch": _spec("bch", "BCHUSDT", 1.637, "BCH", "C"),
    "uni": _spec("uni", "UNIUSDT", 0.0332, "UNI", "C"),
    "aave": _spec("aave", "AAVEUSDT", 0.5867, "AAVE", "C"),
    "pol": _spec("pol", "POLUSDT", 0.001, "POL", "C"),
    "sei": _spec("sei", "SEIUSDT", 0.0012, "SEI", "C"),
    "tia": _spec("tia", "TIAUSDT", 0.0143, "TIA", "C"),
    "op": _spec("op", "OPUSDT", 0.006, "OP", "C"),
    "arb": _spec("arb", "ARBUSDT", 0.0028, "ARB", "C"),
    "paxg": _spec("paxg", "PAXGUSDT", 9.875, "PAXG", "C"),
}

RENKO_ZEC_REGISTRY: dict[str, RenkoAssetSpec] = {
    "zec": _spec("zec", "ZECUSDT", 0.2743, "ZEC", "ZEC"),
}

RENKO_ALT_REGISTRY: dict[str, RenkoAssetSpec] = {
    **RENKO_GROUP_A_REGISTRY,
    **RENKO_GROUP_B_REGISTRY,
    **RENKO_GROUP_C_REGISTRY,
    **RENKO_ZEC_REGISTRY,
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


def merge_enabled_alt_ids(
    group_a_raw: str = "",
    group_b_raw: str = "",
    group_c_raw: str = "",
    *,
    zec_enabled: bool = False,
) -> list[str]:
    """Union of enabled registry alts across rollout groups (order: A, B, C, ZEC)."""
    out: list[str] = []
    seen: set[str] = set()
    for key in (
        *parse_enabled_alt_ids(group_a_raw),
        *parse_enabled_alt_ids(group_b_raw),
        *parse_enabled_alt_ids(group_c_raw),
    ):
        if key not in seen:
            seen.add(key)
            out.append(key)
    if zec_enabled and "zec" not in seen:
        out.append("zec")
    return out
