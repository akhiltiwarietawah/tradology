"""
Backfill Renko trade legs / realized PnL / fees from bot.log + Delta fills.

Does not mark ACTIVE trades COMPLETED or change open positions on exchange.
"""

from __future__ import annotations

import argparse
import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select, update

from src.config.settings import get_settings
from src.exchanges.delta.adapter import DeltaExchangeAdapter
from src.persistence.db import DatabaseManager
from src.persistence.models import TradeLegModel, TradeModel
from src.persistence.renko_trade_repository import _perp_realized_pnl
from src.persistence.trade_repository import to_decimal
from src.strategies.renko_ichimoku.prefix_logger import PrefixLogger


LOG_EXIT = re.compile(
    r"DATABASE: persisted exit trade_id=(RENKO_[A-Z]+_\d+_\d+)"
)
LOG_PNL = re.compile(
    r"\[RENKO_[A-Z]+\] Dynamic sizing exit pnl=\$([-\d.]+)"
)
LOG_FILL = re.compile(
    r"\[RENKO_([A-Z]+)\] Fill applied action=(enter_\w+|exit_\w+) new_pos=(-?\d+) "
    r"fill_px=([\d.]+) order_id=(\d+)"
)
LOG_SIZING = re.compile(
    r"\[RENKO_([A-Z]+)\] Dynamic sizing entry:.*?contract_value=([\d.]+) -> (\d+) contracts"
)

ACTIVE_PROTECT = frozenset(
    {
        "RENKO_ETH_20260918_142",
        "RENKO_SOL_20260921_362",
        "RENKO_XRP_20260921_1287",
    }
)


@dataclass
class RoundTrip:
    trade_id: str
    instance: str
    leg_type: str
    quantity: float
    contract_value: float
    entry_price: float
    exit_price: float
    entry_order_id: str
    exit_order_id: str
    log_gross_pnl: Optional[float] = None


def _brick_index(trade_id: str) -> int:
    return int(trade_id.rsplit("_", 1)[-1])


def _leg_type_from_action(action: str) -> str:
    if "long" in action:
        return "LONG"
    return "SHORT"


def parse_bot_log(path: Path) -> Dict[str, RoundTrip]:
    """Build completed round-trips keyed by trade_id from bot log."""
    lines = path.read_text(errors="replace").splitlines()
    fills: List[Tuple[str, str, float, str, float, float]] = (
        []
    )  # instance, action, px, order_id, cv, qty
    sizing_by_instance: Dict[str, Tuple[float, int]] = {}  # cv, qty at last entry line
    pending_exit_trade: Optional[str] = None
    pending_pnl: Optional[float] = None
    trips: Dict[str, RoundTrip] = {}

    def _resolve_pending_exit(exit_inst: str, exit_action: str, exit_px: float, exit_oid: str) -> None:
        nonlocal pending_exit_trade, pending_pnl
        if not pending_exit_trade:
            return
        tid = pending_exit_trade
        inst = tid.split("_")[1]
        if inst != exit_inst or not exit_action.startswith("exit_"):
            return
        enter_fill = None
        for i in range(len(fills) - 2, -1, -1):
            fi_inst, action, px, oid, cv_i, qty_i = fills[i]
            if fi_inst != inst:
                continue
            if action.startswith("enter_"):
                enter_fill = (action, px, oid, cv_i, qty_i)
                break
        if not enter_fill:
            return
        enter_action, entry_px, entry_oid, cv, qty = enter_fill
        trips[tid] = RoundTrip(
            trade_id=tid,
            instance=inst,
            leg_type=_leg_type_from_action(enter_action),
            quantity=float(qty),
            contract_value=cv,
            entry_price=entry_px,
            exit_price=exit_px,
            entry_order_id=entry_oid,
            exit_order_id=exit_oid,
            log_gross_pnl=pending_pnl,
        )
        pending_exit_trade = None
        pending_pnl = None

    for line in lines:
        m_sz = LOG_SIZING.search(line)
        if m_sz:
            inst, cv, qty = m_sz.group(1), float(m_sz.group(2)), int(m_sz.group(3))
            sizing_by_instance[inst] = (cv, qty)

        m_exit = LOG_EXIT.search(line)
        if m_exit:
            pending_exit_trade = m_exit.group(1)
            pending_pnl = None
            continue

        if pending_exit_trade and pending_pnl is None:
            m_pnl = LOG_PNL.search(line)
            if m_pnl:
                pending_pnl = float(m_pnl.group(1))
                continue

        m_fill = LOG_FILL.search(line)
        if m_fill:
            inst, action, _pos, px, oid = (
                m_fill.group(1),
                m_fill.group(2),
                m_fill.group(3),
                float(m_fill.group(4)),
                m_fill.group(5),
            )
            cv, qty = sizing_by_instance.get(inst, (1.0, 0))
            fills.append((inst, action, px, oid, cv, float(qty)))
            if action.startswith("exit_"):
                _resolve_pending_exit(inst, action, px, oid)
            continue

    return trips


def _fill_commission(fill: dict) -> float:
    commission = fill.get("commission") or fill.get("fees") or 0.0
    try:
        return abs(float(commission))
    except (TypeError, ValueError):
        return 0.0


async def fees_for_orders(
    adapter: DeltaExchangeAdapter,
    product_id: str,
    order_ids: List[str],
) -> float:
    want = {str(o) for o in order_ids if o}
    if not want:
        return 0.0
    fills = await adapter.get_recent_fills_for_product(
        instrument_id=str(product_id),
        side=None,
        page_size=50,
    )
    total = 0.0
    for f in fills:
        oid = str(f.get("order_id") or "")
        if oid in want:
            total += _fill_commission(f)
    return round(total, 4)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, default=Path("logs/bot.log"))
    parser.add_argument(
        "--since",
        default="2026-09-18",
        help="Only COMPLETED trades with trade_id date >= YYYY-MM-DD (from id)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-older-completed", action="store_true")
    args = parser.parse_args()

    since_tag = args.since.replace("-", "")
    trips = parse_bot_log(args.log)
    settings = get_settings()
    db = DatabaseManager(settings)
    await db.connect()

    key, secret = settings.renko_api_credentials()
    adapter = DeltaExchangeAdapter(
        rest_url=settings.active_rest_url,
        ws_url=settings.active_ws_url,
        api_key=key,
        api_secret=secret,
        is_testnet=settings.delta_env.value != "live",
        logger=PrefixLogger(__import__("logging").getLogger("backfill"), "RENKO"),
    )
    await adapter.initialize()

    product_by_inst = {"ETH": "3136", "SOL": None, "XRP": None}
    for name in ("sol", "xrp", "eth"):
        p = Path(f"data/renko_ichimoku_{name}_state_live.json")
        if p.exists():
            import json

            st = json.loads(p.read_text())
            sym = st.get("symbol", "")
            inst = name.upper()
            if st.get("instrument_id"):
                product_by_inst[inst] = str(st["instrument_id"])

    updated = 0
    async with db.get_session() as session:
        for tid, trip in sorted(trips.items()):
            date_part = tid.split("_")[2]
            if not args.include_older_completed and date_part < since_tag:
                continue
            trade = (
                await session.execute(select(TradeModel).where(TradeModel.trade_id == tid))
            ).scalar_one_or_none()
            if not trade:
                continue
            if trade.status == "ACTIVE" and tid in ACTIVE_PROTECT:
                print(f"SKIP protected ACTIVE {tid}")
                continue

            cfg = trade.strategy_config or {}
            product_id = str(cfg.get("product_id") or product_by_inst.get(trip.instance) or "")
            fees = await fees_for_orders(
                adapter, product_id, [trip.entry_order_id, trip.exit_order_id]
            )
            qty = to_decimal(trip.quantity)
            cv = to_decimal(trip.contract_value)
            entry_px = to_decimal(trip.entry_price)
            exit_px = to_decimal(trip.exit_price)
            realized = _perp_realized_pnl(trip.leg_type, entry_px, exit_px, qty, cv)
            fee_dec = to_decimal(fees)
            net = realized - fee_dec
            leg_id = f"{tid}_{trip.leg_type}"

            if trip.log_gross_pnl is not None:
                diff = abs(float(realized) - trip.log_gross_pnl)
                if diff > 0.05:
                    print(
                        f"WARN {tid}: computed gross {realized} vs log {trip.log_gross_pnl} (diff={diff:.4f})"
                    )

            print(
                f"{tid} {trade.status} qty={trip.quantity} gross={realized} fees={fee_dec} net={net} "
                f"orders={trip.entry_order_id}/{trip.exit_order_id}"
            )

            if args.dry_run:
                continue

            if trade.status == "COMPLETED":
                await session.execute(
                    update(TradeModel)
                    .where(TradeModel.trade_id == tid)
                    .values(
                        realized_pnl=realized,
                        total_fees=fee_dec,
                        net_pnl=net,
                        total_entry_premium=round(entry_px * qty * cv, 4),
                        total_exit_premium=round(exit_px * qty * cv, 4),
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                await session.execute(
                    update(TradeLegModel)
                    .where(TradeLegModel.leg_id == leg_id)
                    .values(
                        quantity=qty,
                        entry_price=entry_px,
                        exit_price=exit_px,
                        realized_pnl=realized,
                        fees=fee_dec,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                updated += 1

        # Fix ACTIVE open legs: quantity + entry notional only
        for active_tid in ACTIVE_PROTECT:
            trade = (
                await session.execute(select(TradeModel).where(TradeModel.trade_id == active_tid))
            ).scalar_one_or_none()
            if not trade or trade.status != "ACTIVE":
                continue
            import json

            inst = active_tid.split("_")[1]
            p = Path(f"data/renko_ichimoku_{inst.lower()}_state_live.json")
            if not p.exists():
                continue
            st = json.loads(p.read_text())
            qty_f = float(st.get("open_quantity") or 0)
            entry_px_f = float(st.get("entry_price") or 0)
            cv = float((trade.strategy_config or {}).get("contract_value") or 0.01)
            if inst in ("SOL", "XRP"):
                cv = 1.0
            if inst == "ETH":
                cv = 0.01
            leg_type = "LONG" if float(st.get("position", 0)) > 0 else "SHORT"
            leg_id = f"{active_tid}_{leg_type}"
            qty = to_decimal(qty_f)
            entry_px = to_decimal(entry_px_f)
            cv_d = to_decimal(cv)
            entry_notional = round(entry_px * qty * cv_d, 4)
            print(
                f"ACTIVE fix {active_tid} qty={qty_f} entry_notional={entry_notional} (status stays ACTIVE)"
            )
            if args.dry_run:
                continue
            await session.execute(
                update(TradeModel)
                .where(TradeModel.trade_id == active_tid)
                .values(
                    total_entry_premium=entry_notional,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.execute(
                update(TradeLegModel)
                .where(TradeLegModel.leg_id == leg_id)
                .values(
                    quantity=qty,
                    entry_price=entry_px,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            updated += 1

        if not args.dry_run:
            await session.commit()

    await adapter.close()
    await db.disconnect()
    print(f"Done. rows touched: {updated}")


if __name__ == "__main__":
    asyncio.run(main())
