"""Main entrypoint for Tradology BTC Options Trading Engine."""

import sys
import os
import argparse
import asyncio
import signal
import uvicorn

from src.config.settings import Settings, get_settings, Environment
from src.engine import TradingEngine
from src.api.app import create_app


def parse_args():
    parser = argparse.ArgumentParser(description="Tradology BTC Options 0DTE Short Strangle Trading Engine")
    parser.add_argument(
        "--env",
        choices=["testnet", "live"],
        help="Execution environment (overrides DELTA_ENV in .env). Default is testnet.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run in dry-run simulation mode without submitting real orders.",
    )
    parser.add_argument(
        "--api",
        action="store_true",
        help="Launch FastAPI HTTP server alongside the trading engine.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current engine status and trade state without running loop.",
    )
    parser.add_argument(
        "--reconcile-only",
        action="store_true",
        help="Run one-shot state reconciliation against exchange and exit.",
    )
    return parser.parse_args()


async def run_engine_cli(engine: TradingEngine, reconcile_only: bool = False, show_status: bool = False):
    """Run engine in standalone CLI mode."""
    if show_status:
        trade, history = engine.state_persistence.load_state()
        print("\n" + "=" * 50)
        print("TRADING ENGINE STATUS SNAPSHOT")
        print("=" * 50)
        print(f"Environment: {engine.settings.delta_env.value.upper()}")
        print(f"Dry Run: {engine.settings.dry_run} | Kill Switch: {engine.settings.kill_switch}")
        print(f"Active Trade: {trade.strategy_trade_id if trade else 'None'}")
        if trade:
            print(f"State: {trade.state.value}")
            print(f"Realized PnL: ${trade.total_realized_pnl:.2f}")
            print(f"Unrealized PnL: ${trade.total_unrealized_pnl:.2f}")
            if trade.ce_leg:
                print(f"CE Leg: {trade.ce_leg.symbol} (Status: {trade.ce_leg.status.value}, Fill: ${trade.ce_leg.entry_fill_price}, SL: ${trade.ce_leg.sl_price})")
            if trade.pe_leg:
                print(f"PE Leg: {trade.pe_leg.symbol} (Status: {trade.pe_leg.status.value}, Fill: ${trade.pe_leg.entry_fill_price}, SL: ${trade.pe_leg.sl_price})")

        # Fetch and display live authenticated account balances
        try:
            acc_bal = await engine.get_account_balances()
            print("\n" + "-" * 50)
            print("ACCOUNT BALANCES (Delta Exchange India)")
            print("-" * 50)
            has_balances = False
            for sym, b in acc_bal.balances.items():
                if b.balance > 0 or b.available_balance > 0 or sym in ("USD", "INR", "BTC"):
                    has_balances = True
                    inr_str = f" | INR Equiv: ₹{b.balance_inr:,.2f}" if b.balance_inr is not None and sym != "INR" else ""
                    print(f"  [{sym:<4}] Balance: {b.balance:>10.4f} | Available: {b.available_balance:>10.4f} | Blocked: {b.blocked_margin:>8.4f}{inr_str}")
            if not has_balances:
                print("  No active balances found.")
        except Exception as e:
            print(f"\n  [Account Balance]: Unable to query ({e})")
        finally:
            await engine.delta_adapter.rest_client.close()

        from src.analytics.ledger import TradeLedgerAnalytics
        analytics = TradeLedgerAnalytics(trades_log_path=f"{engine.settings.logs_dir}/trades.jsonl")
        trades = analytics.load_completed_trades(fallback_history=history)
        stats = analytics.compute_summary_statistics(trades)
        if stats["total_trades"] > 0:
            print("\n" + "-" * 50)
            print("TRADE LEDGER PERFORMANCE SUMMARY")
            print("-" * 50)
            print(f"Total Trades: {stats['total_trades']} | Win Rate: {stats['win_rate_pct']}% ({stats['winning_trades']}W / {stats['losing_trades']}L)")
            print(f"Total Realized PnL: ${stats['total_realized_pnl']:.2f} | Net PnL (after fees): ${stats['net_pnl']:.2f}")
            print(f"Profit Factor: {stats['profit_factor']:.2f}")
        print("=" * 50 + "\n")
        return

    if reconcile_only:
        await engine.exchange_service.initialize_all()
        recovered_trade, _ = engine.state_persistence.load_state()
        engine.strategy.current_trade = recovered_trade
        res = await engine.reconcile_state()
        print(f"\nReconciliation result: Synchronized={res.is_synchronized}, Status={res.status}")
        await engine.exchange_service.close_all()
        return

    # Setup signal handlers for graceful exit
    stop_event = asyncio.Event()

    def _signal_handler():
        engine.logger.info("Received termination signal. Initiating graceful shutdown...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    await engine.start()
    try:
        await stop_event.wait()
    finally:
        await engine.stop()


def main():
    args = parse_args()

    # Load settings with optional CLI override
    env_override = {}
    if args.env:
        env_override["delta_env"] = args.env
    if args.dry_run:
        env_override["dry_run"] = True

    try:
        settings = Settings(**env_override)
    except Exception as e:
        print(f"Configuration Error: {e}", file=sys.stderr)
        sys.exit(1)

    engine = TradingEngine(settings=settings)

    if args.api:
        # Run FastAPI app with uvicorn
        app = create_app(engine)
        uvicorn.run(
            app,
            host=settings.server_host,
            port=settings.server_port,
            log_level=settings.log_level.lower(),
            access_log=False,
        )
    else:
        # Run async event loop
        asyncio.run(run_engine_cli(engine, reconcile_only=args.reconcile_only, show_status=args.status))


if __name__ == "__main__":
    main()
