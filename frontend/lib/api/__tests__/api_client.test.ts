import { describe, expect, it, beforeEach, afterEach, mock } from "bun:test";
import { ApiClient, ApiClientError } from "../client";
import {
  HealthResponseSchema,
  ReadinessResponseSchema,
  SystemStatusSchema,
  PerformanceMetricsSchema,
} from "../schemas";

describe("ApiClient & Zod Schemas", () => {
  let client: ApiClient;
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    client = new ApiClient("http://localhost:8000", 1000);
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  describe("Schema Validation", () => {
    it("validates health response correctly", () => {
      const valid = { status: "ok" };
      const res = HealthResponseSchema.safeParse(valid);
      expect(res.success).toBe(true);
      if (res.success) {
        expect(res.data.status).toBe("ok");
      }
    });

    it("validates readiness response correctly", () => {
      const valid = {
        ready: true,
        engine: "RUNNING",
        exchange: "AVAILABLE",
        reconciliation: "SYNCHRONIZED",
      };
      const res = ReadinessResponseSchema.safeParse(valid);
      expect(res.success).toBe(true);
      if (res.success) {
        expect(res.data.ready).toBe(true);
        expect(res.data.engine).toBe("RUNNING");
      }
    });

    it("validates comprehensive system status payload correctly", () => {
      const sampleStatus = {
        engine: {
          status: "RUNNING",
          uptime_seconds: 450.2,
          start_time: "2026-09-01T09:00:00+00:00",
          environment: "TESTNET",
          dry_run: false,
          kill_switch: false,
          strategy_name: "short_strangle",
          strategy_active: true,
        },
        exchange: {
          rest_connected: true,
          ws_connected: true,
          last_rest_request_time: "2026-09-01T09:05:00+00:00",
          last_ws_tick_time: "2026-09-01T09:05:02+00:00",
          ws_stale: false,
        },
        reconciliation: {
          is_synchronized: true,
          status: "SYNCHRONIZED",
          last_reconciliation_time: "2026-09-01T09:05:00+00:00",
          latest_discrepancy: null,
        },
        database: {
          connected: true,
          status: "AVAILABLE",
          last_db_operation: "2026-09-01T09:05:00+00:00",
        },
        watchdog: {
          last_heartbeat: "2026-09-01T09:05:03+00:00",
          last_loop: "2026-09-01T09:05:03+00:00",
        },
        current_trade: {
          trade_id: "STRANGLE_20260901_090000",
          strategy_name: "short_strangle",
          trade_state: "ACTIVE",
          entry_timestamp: "2026-09-01T09:00:05+00:00",
          ce_symbol: "C-BTC-98000-010926",
          pe_symbol: "P-BTC-92000-010926",
          ce_status: "OPEN",
          pe_status: "OPEN",
          ce_entry_price: 102.5,
          pe_entry_price: 98.0,
          ce_sl_price: 205.0,
          pe_sl_price: 196.0,
          ce_native_bracket_active: true,
          pe_native_bracket_active: true,
          ce_bracket_order_id: "BRK_150401_205",
          pe_bracket_order_id: "BRK_150402_196",
        },
        alerts: {
          recent_count: 1,
          recent_alerts: [
            {
              timestamp: "2026-09-01T09:00:05+00:00",
              severity: "SUCCESS",
              event: "ENTRY_FILLED",
              message: "Strangle entry confirmed",
            },
          ],
        },
        status: "RUNNING",
        environment: "TESTNET",
        kill_switch: false,
        connected_exchange: true,
        strategy: "short_strangle",
        strategy_active: true,
        trading_enabled: true,
        underlying: "BTC",
      };

      const res = SystemStatusSchema.safeParse(sampleStatus);
      expect(res.success).toBe(true);
      if (res.success) {
        expect(res.data.engine.status).toBe("RUNNING");
        expect(res.data.current_trade?.trade_id).toBe("STRANGLE_20260901_090000");
        expect(res.data.current_trade?.ce_native_bracket_active).toBe(true);
      }
    });

    it("validates performance metrics schema correctly", () => {
      const samplePerformance = {
        total_trades: 5,
        winning_trades: 4,
        losing_trades: 1,
        breakeven_trades: 0,
        win_rate: 80.0,
        loss_rate: 20.0,
        total_realized_pnl: 380.0,
        total_fees: 15.0,
        net_pnl: 365.0,
        gross_profit: 480.0,
        gross_loss: 100.0,
        profit_factor: 4.8,
        average_trade_pnl: 73.0,
        average_win: 120.0,
        average_loss: -100.0,
        payoff_ratio: 1.2,
        max_drawdown_amount: 100.0,
        max_drawdown_pct: 15.5,
        sharpe_ratio: 2.1,
        sortino_ratio: 3.4,
        calmar_ratio: 3.65,
        current_streak: 2,
        max_consecutive_wins: 3,
        max_consecutive_losses: 1,
        largest_winning_trade: 150.0,
        largest_losing_trade: -100.0,
        cumulative_pnl_curve: [
          {
            trade_id: "T1",
            trade_date: "2026-08-25",
            realized_pnl: 100,
            net_pnl: 97,
            cumulative_pnl: 97,
            drawdown: 0,
            drawdown_pct: 0,
          },
        ],
        daily_pnl: [
          {
            date: "2026-08-25",
            trades_count: 1,
            realized_pnl: 100,
            fees: 3,
            net_pnl: 97,
            win_rate: 100,
          },
        ],
        monthly_pnl: [
          {
            month: "2026-08",
            trades_count: 1,
            realized_pnl: 100,
            fees: 3,
            net_pnl: 97,
            win_rate: 100,
          },
        ],
        strategy_breakdown: {},
        exchange_breakdown: {},
      };

      const res = PerformanceMetricsSchema.safeParse(samplePerformance);
      expect(res.success).toBe(true);
      if (res.success) {
        expect(res.data.total_trades).toBe(5);
        expect(res.data.net_pnl).toBe(365.0);
        expect(res.data.cumulative_pnl_curve.length).toBe(1);
      }
    });
  });

  describe("ApiClient HTTP Calls", () => {
    it("successfully fetches and parses /health", async () => {
      globalThis.fetch = mock(() =>
        Promise.resolve(
          new Response(JSON.stringify({ status: "ok" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        )
      ) as any;

      const health = await client.getHealth();
      expect(health.status).toBe("ok");
    });

    it("successfully fetches and parses /ready", async () => {
      globalThis.fetch = mock(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              ready: true,
              engine: "RUNNING",
              exchange: "AVAILABLE",
              reconciliation: "SYNCHRONIZED",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          )
        )
      ) as any;

      const ready = await client.getReadiness();
      expect(ready.ready).toBe(true);
      expect(ready.engine).toBe("RUNNING");
    });

    it("constructs query string correctly for getPerformance", async () => {
      let capturedUrl = "";
      globalThis.fetch = mock((url: string | URL | Request) => {
        capturedUrl = url.toString();
        return Promise.resolve(
          new Response(
            JSON.stringify({
              total_trades: 0,
              net_pnl: 0,
              cumulative_pnl_curve: [],
              daily_pnl: [],
              monthly_pnl: [],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          )
        );
      }) as any;

      await client.getPerformance({
        start_date: "2026-08-01",
        end_date: "2026-09-01",
        strategy_name: "short_strangle",
      });

      expect(capturedUrl).toContain("start_date=2026-08-01");
      expect(capturedUrl).toContain("end_date=2026-09-01");
      expect(capturedUrl).toContain("strategy_name=short_strangle");
    });

    it("throws ApiClientError with statusCode on HTTP 500", async () => {
      globalThis.fetch = mock(() =>
        Promise.resolve(
          new Response(JSON.stringify({ error: "Internal Server Error" }), {
            status: 500,
            headers: { "Content-Type": "application/json" },
          })
        )
      ) as any;

      expect(client.getStatus()).rejects.toThrow(ApiClientError);
      try {
        await client.getStatus();
      } catch (e: any) {
        expect(e.statusCode).toBe(500);
      }
    });

    it("handles connection refused / network error cleanly", async () => {
      globalThis.fetch = mock(() =>
        Promise.reject(new Error("connect ECONNREFUSED 127.0.0.1:8000"))
      ) as any;

      try {
        await client.getStatus();
        expect(true).toBe(false); // Should not reach here
      } catch (e: any) {
        expect(e instanceof ApiClientError).toBe(true);
        expect(e.isNetworkError).toBe(true);
      }
    });

    it("correctly normalizes nested PerformanceService summary and drawdown response", async () => {
      const nestedBackendPayload = {
        status: "ok",
        source: "postgresql",
        period: { from: null, to: null },
        summary: {
          trade_count: 8,
          winning_trades: 6,
          losing_trades: 2,
          breakeven_trades: 0,
          win_rate_pct: "75.00%",
          gross_profit: "600.0000",
          gross_loss: "150.0000",
          total_realized_pnl: "450.0000",
          total_fees: "24.5000",
          net_pnl: "425.5000",
          profit_factor: "4.0000",
          average_trade_pnl: "53.1875",
          average_winning_trade: "100.0000",
          average_losing_trade: "-75.0000",
          largest_winning_trade: "120.0000",
          largest_losing_trade: "-80.0000",
          max_consecutive_wins: 4,
          max_consecutive_losses: 1,
        },
        drawdown: {
          current_cumulative_pnl: "425.5000",
          peak_cumulative_pnl: "450.0000",
          current_drawdown: "24.5000",
          max_drawdown: "80.0000",
        },
        daily: [
          {
            date: "2026-09-01",
            trade_count: 2,
            wins: 2,
            losses: 0,
            gross_profit: "150.0000",
            gross_loss: "0.0000",
            fees: "6.0000",
            net_pnl: "144.0000",
          },
        ],
        monthly: [
          {
            month: "2026-09",
            trade_count: 2,
            wins: 2,
            losses: 0,
            fees: "6.0000",
            net_pnl: "144.0000",
            win_rate_pct: "100.00%",
          },
        ],
      };

      globalThis.fetch = mock(() =>
        Promise.resolve(
          new Response(JSON.stringify(nestedBackendPayload), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        )
      ) as any;

      const normalized = await client.getPerformance();
      expect(normalized.total_trades).toBe(8);
      expect(normalized.winning_trades).toBe(6);
      expect(normalized.losing_trades).toBe(2);
      expect(normalized.win_rate).toBe(75.0);
      expect(normalized.net_pnl).toBe(425.5);
      expect(normalized.total_fees).toBe(24.5);
      expect(normalized.max_drawdown_amount).toBe(80.0);
      expect(normalized.daily_pnl.length).toBe(1);
      expect(normalized.daily_pnl[0].net_pnl).toBe(144.0);
    });

  });
});
