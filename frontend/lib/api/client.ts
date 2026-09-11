import {
  HealthResponseSchema,
  ReadinessResponseSchema,
  SystemStatusSchema,
  PerformanceMetricsSchema,
  RenkoTradesResponseSchema,
  type HealthResponse,
  type ReadinessResponse,
  type SystemStatusResponse,
  type PerformanceMetricsResponse,
  type RenkoTradesResponse,
} from "./schemas";

export class ApiClientError extends Error {
  public statusCode?: number;
  public endpoint: string;
  public isNetworkError: boolean;
  public isTimeout: boolean;
  public details?: any;

  constructor(
    message: string,
    endpoint: string,
    options?: {
      statusCode?: number;
      isNetworkError?: boolean;
      isTimeout?: boolean;
      details?: any;
    }
  ) {
    super(message);
    this.name = "ApiClientError";
    this.endpoint = endpoint;
    this.statusCode = options?.statusCode;
    this.isNetworkError = options?.isNetworkError || false;
    this.isTimeout = options?.isTimeout || false;
    this.details = options?.details;
  }
}

export interface PerformanceQueryParams {
  start_date?: string;
  end_date?: string;
  strategy_name?: string;
  exchange?: string;
}

export class ApiClient {
  private baseUrl: string;
  private defaultTimeout: number;

  constructor(baseUrl?: string, timeout: number = 6000) {
    if (baseUrl) {
      this.baseUrl = baseUrl.replace(/\/$/, "");
    } else if (typeof window !== "undefined") {
      // In the browser, make same-origin requests through the server-side API proxy
      this.baseUrl = "/api/proxy";
    } else {
      // Server-side SSR / testing: direct connection to internal FastAPI backend
      this.baseUrl = (
        process.env.FASTAPI_BACKEND_URL ||
        process.env.NEXT_PUBLIC_API_URL ||
        "http://127.0.0.1:8000"
      ).replace(/\/$/, "");
    }
    this.defaultTimeout = timeout;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {},
    timeoutMs?: number
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;
    const controller = new AbortController();
    const timeout = setTimeout(
      () => controller.abort(),
      timeoutMs || this.defaultTimeout
    );

    const headers: Record<string, string> = {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...((options.headers as Record<string, string>) || {}),
    };

    try {
      const response = await fetch(url, {
        ...options,
        signal: controller.signal,
        headers,
      });

      clearTimeout(timeout);

      if (!response.ok) {
        let errBody: any;
        try {
          errBody = await response.json();
        } catch {
          errBody = await response.text();
        }
        throw new ApiClientError(
          `API request failed with HTTP ${response.status}: ${typeof errBody === "string" ? errBody : JSON.stringify(errBody)}`,
          endpoint,
          {
            statusCode: response.status,
            details: errBody,
          }
        );
      }

      return (await response.json()) as T;
    } catch (err: any) {
      clearTimeout(timeout);

      if (err instanceof ApiClientError) {
        throw err;
      }

      if (err.name === "AbortError") {
        throw new ApiClientError(
          `API request to ${endpoint} timed out after ${timeoutMs || this.defaultTimeout}ms`,
          endpoint,
          { isTimeout: true }
        );
      }

      throw new ApiClientError(
        `Failed to connect to FastAPI backend at ${this.baseUrl}${endpoint}: ${err.message}`,
        endpoint,
        { isNetworkError: true, details: err }
      );
    }
  }

  /**
   * Check backend process liveness
   */
  async getHealth(): Promise<HealthResponse> {
    const data = await this.request<any>("/health");
    const parsed = HealthResponseSchema.safeParse(data);
    if (!parsed.success) {
      return { status: "ok" };
    }
    return parsed.data;
  }

  /**
   * Check trading readiness (RUNNING, Exchange available, Reconciliation synchronized)
   */
  async getReadiness(): Promise<ReadinessResponse> {
    const data = await this.request<any>("/ready");
    const parsed = ReadinessResponseSchema.safeParse(data);
    if (!parsed.success) {
      throw new ApiClientError("Invalid readiness response structure from backend", "/ready", {
        details: parsed.error.format(),
      });
    }
    return parsed.data;
  }

  /**
   * Get comprehensive live system status (Engine, Exchange, Reconciliation, DB, Watchdog, Current Trade, Alerts)
   */
  async getStatus(): Promise<SystemStatusResponse> {
    const data = await this.request<any>("/api/v1/status");
    const parsed = SystemStatusSchema.safeParse(data);
    if (!parsed.success) {
      // In case of slight schema differences, return data with graceful fallback
      console.warn("[ApiClient] /api/v1/status schema validation warning:", parsed.error);
      return data as SystemStatusResponse;
    }
    return parsed.data;
  }

  /**
   * Get historical performance metrics, equity curve, daily/monthly breakdown
   */
  async getPerformance(params?: PerformanceQueryParams): Promise<PerformanceMetricsResponse> {
    const query = new URLSearchParams();
    if (params?.start_date) query.set("start_date", params.start_date);
    if (params?.end_date) query.set("end_date", params.end_date);
    if (params?.strategy_name) query.set("strategy_name", params.strategy_name);
    if (params?.exchange) query.set("exchange", params.exchange);

    const queryString = query.toString();
    const endpoint = `/api/v1/performance${queryString ? `?${queryString}` : ""}`;
    const data = await this.request<any>(endpoint);

    // Normalize nested summary structure from PerformanceService if present
    if (data && data.summary) {
      const s = data.summary;
      const dd = data.drawdown || {};
      const winRateNum = typeof s.win_rate_pct === "string" ? parseFloat(s.win_rate_pct) || 0 : (s.win_rate_pct || 0);

      const normalized: PerformanceMetricsResponse = {
        total_trades: Number(s.trade_count || 0),
        winning_trades: Number(s.winning_trades || 0),
        losing_trades: Number(s.losing_trades || 0),
        breakeven_trades: Number(s.breakeven_trades || 0),
        win_rate: winRateNum,
        loss_rate: 100 - winRateNum,
        total_realized_pnl: parseFloat(s.total_realized_pnl || "0") || 0,
        total_fees: parseFloat(s.total_fees || "0") || 0,
        net_pnl: parseFloat(s.net_pnl || "0") || 0,
        gross_profit: parseFloat(s.gross_profit || "0") || 0,
        gross_loss: parseFloat(s.gross_loss || "0") || 0,
        profit_factor: parseFloat(s.profit_factor || "0") || 0,
        average_trade_pnl: parseFloat(s.average_trade_pnl || "0") || 0,
        average_win: parseFloat(s.average_winning_trade || "0") || 0,
        average_loss: parseFloat(s.average_losing_trade || "0") || 0,
        payoff_ratio: (parseFloat(s.average_losing_trade || "0") !== 0) ? Math.abs(parseFloat(s.average_winning_trade || "0") / parseFloat(s.average_losing_trade || "1")) : 0,
        max_drawdown_amount: parseFloat(dd.max_drawdown || "0") || 0,
        max_drawdown_pct: 0,
        sharpe_ratio: 0,
        sortino_ratio: 0,
        calmar_ratio: 0,
        current_streak: Number(s.max_consecutive_wins || 0),
        max_consecutive_wins: Number(s.max_consecutive_wins || 0),
        max_consecutive_losses: Number(s.max_consecutive_losses || 0),
        largest_winning_trade: parseFloat(s.largest_winning_trade || "0") || 0,
        largest_losing_trade: parseFloat(s.largest_losing_trade || "0") || 0,
        cumulative_pnl_curve: Array.isArray(data.cumulative_pnl_curve) ? data.cumulative_pnl_curve : [],
        daily_pnl: Array.isArray(data.daily) ? data.daily.map((d: any) => ({
          date: d.date,
          trades_count: Number(d.trade_count || 0),
          realized_pnl: (parseFloat(d.gross_profit || "0") || 0) - (parseFloat(d.gross_loss || "0") || 0),
          fees: parseFloat(d.fees || "0") || 0,
          net_pnl: parseFloat(d.net_pnl || "0") || 0,
          win_rate: Number(d.trade_count ? (Number(d.wins || 0) / Number(d.trade_count)) * 100 : 0),
        })) : [],
        monthly_pnl: Array.isArray(data.monthly) ? data.monthly.map((m: any) => ({
          month: m.month,
          trades_count: Number(m.trade_count || 0),
          realized_pnl: (parseFloat(m.net_pnl || "0") || 0) + (parseFloat(m.fees || "0") || 0),
          fees: parseFloat(m.fees || "0") || 0,
          net_pnl: parseFloat(m.net_pnl || "0") || 0,
          win_rate: parseFloat(m.win_rate_pct || "0") || 0,
        })) : [],
        strategy_breakdown: {},
        exchange_breakdown: {},
      };
      return normalized;
    }

    const parsed = PerformanceMetricsSchema.safeParse(data);
    if (!parsed.success) {
      console.warn("[ApiClient] /api/v1/performance schema validation warning:", parsed.error);
      return data as PerformanceMetricsResponse;
    }
    return parsed.data;
  }

  /**
   * Get Renko Ichimoku trade history from PostgreSQL
   */
  async getRenkoTrades(limit: number = 50): Promise<RenkoTradesResponse> {
    const data = await this.request<any>(`/api/v1/renko/trades?limit=${limit}`);
    const parsed = RenkoTradesResponseSchema.safeParse(data);
    if (!parsed.success) {
      console.warn("[ApiClient] /api/v1/renko/trades schema validation warning:", parsed.error);
      return data as RenkoTradesResponse;
    }
    return parsed.data;
  }
}

export const apiClient = new ApiClient();
