"""Per-symbol Renko Ichimoku instance configuration."""

from __future__ import annotations

from dataclasses import dataclass

from src.strategies.renko_ichimoku.asset_registry import DEFAULT_RENKO_SIZING_BASE_USD


@dataclass(frozen=True)
class RenkoInstanceConfig:
    """One live Renko+Ichimoku stream (symbol, box, size, state file)."""

    instance_id: str
    strategy_code: str
    symbol: str
    box_size: float
    position_size: float
    state_file: str
    candle_resolution: str = "15m"
    flatten: bool = False
    position_sizing_mode: str = "fixed"
    sizing_base_usd: float = DEFAULT_RENKO_SIZING_BASE_USD
    margin_pct: float = 0.25
    leverage: float = 10.0
    profit_retain_pct: float = 0.5
    account_name: str = "renko"
    api_key: str = ""
    api_secret: str = ""


RENKO_ETH_STRATEGY_CODE = "renko_ichimoku_eth"
RENKO_SOL_STRATEGY_CODE = "renko_ichimoku_sol"
RENKO_XRP_STRATEGY_CODE = "renko_ichimoku_xrp"
RENKO_XRP2_STRATEGY_CODE = "renko_ichimoku_xrp2"
RENKO_LEGACY_STRATEGY_CODE = "renko_ichimoku"


def parse_coin_accounts(raw: str) -> dict[str, str]:
    """Map coin id → wallet label. Format: `sui:strangle,xrp:strangle`."""
    out: dict[str, str] = {}
    for part in str(raw or "").replace(";", ",").split(","):
        piece = part.strip().lower()
        if ":" not in piece:
            continue
        coin, wallet = piece.split(":", 1)
        coin = "".join(ch for ch in coin.strip() if ch.isalnum())
        wallet = wallet.strip()
        if not coin or not wallet:
            continue
        out[coin] = wallet
    return out


def parse_account_books(raw: str) -> list[tuple[str, str, float | None]]:
    """Parse `coin:wallet` or `coin:wallet:sizing_base`. Box size is not in this line."""
    out: list[tuple[str, str, float | None]] = []
    seen: set[tuple[str, str]] = set()
    for part in str(raw or "").replace(";", ",").split(","):
        bits = [bit.strip() for bit in part.strip().lower().split(":")]
        if len(bits) not in (2, 3):
            continue
        base = "".join(ch for ch in bits[0] if ch.isalnum())
        account = "".join(ch for ch in bits[1] if ch.isalnum())
        if not base or not account:
            continue
        sizing: float | None = None
        if len(bits) == 3 and bits[2]:
            try:
                sizing = float(bits[2])
            except ValueError:
                continue
            if sizing <= 0:
                continue
        key = (base, account)
        if key in seen:
            continue
        seen.add(key)
        out.append((base, account, sizing))
    return out


def book_instance_id(base_id: str, account_slug: str, taken_ids: set[str]) -> str:
    """Stable id whose first 4 characters do not collide with an existing book."""
    taken_prefix = {item.upper()[:4] for item in taken_ids}
    slug = account_slug[:8]
    candidate = f"{base_id}_{slug}"
    n = 2
    while candidate in taken_ids or candidate.upper()[:4] in taken_prefix:
        candidate = f"{base_id}{n}_{slug}"
        n += 1
        if n > 30:
            break
    return candidate
