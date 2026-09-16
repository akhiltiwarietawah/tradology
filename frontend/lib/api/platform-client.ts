import { apiClient } from "@/lib/api/client";

export interface PlatformUser {
  id: string;
  email: string;
  name?: string | null;
  avatar_url?: string | null;
}

export interface PlatformStrategy {
  id: string;
  code: string;
  name: string;
  description?: string | null;
  supported_exchanges: string[];
  markets: string[];
  timeframe?: string | null;
  risk_profile?: string | null;
  metadata?: Record<string, unknown>;
}

export interface PlatformExchangeAccount {
  id: string;
  exchange: string;
  label: string;
  account_name?: string;
  status?: string;
  health_status?: string;
  connection_status: string;
  balance?: number;
  equity?: number;
  available_balance?: number;
  unrealized_pnl?: number;
  realized_pnl?: number;
  currency?: string;
  last_synced_at?: string | null;
  last_sync_at?: string | null;
  last_successful_sync_at?: string | null;
  last_error?: string | null;
  is_testnet: boolean;
}

export interface EquityCurvePoint {
  timestamp: string;
  equity: number;
  available_balance?: number;
  unrealized_pnl?: number;
}

export interface AccountPosition {
  symbol: string;
  side: string;
  quantity: number;
  entry_price?: number | null;
  mark_price?: number | null;
  unrealized_pnl?: number;
  realized_pnl?: number;
  leverage?: number | null;
  liquidation_price?: number | null;
}

export interface AccountOrder {
  exchange_order_id: string;
  symbol: string;
  side: string;
  order_type?: string | null;
  quantity: number;
  price?: number | null;
  status?: string | null;
}

export interface AccountDetailResponse {
  account: PlatformExchangeAccount;
  positions: AccountPosition[];
  orders: AccountOrder[];
}

export interface DashboardSummary {
  user: { id: string; email: string; name?: string | null };
  connected_accounts_count: number;
  active_subscriptions_count: number;
  total_equity: number;
  total_available_balance: number;
  total_unrealized_pnl: number;
  accounts: PlatformExchangeAccount[];
  subscriptions: Array<{
    id: string;
    status: string;
    strategy?: PlatformStrategy;
    linked_accounts?: Array<{ exchange_account_id: string; status: string }>;
  }>;
  equity_curve: EquityCurvePoint[];
  engine?: { status?: string; environment?: string };
}

export type EquityRange = "1D" | "1W" | "1M" | "3M" | "ALL";

export interface PlatformTrade {
  trade_id: string;
  strategy: string;
  strategy_account_id?: string | null;
  account_id?: string | null;
  entry?: number;
  exit?: number;
  quantity?: number | null;
  realized_pnl: number;
  net_pnl?: number;
  fees: number;
  funding?: number;
  status: string;
  opened_at?: string | null;
  closed_at?: string | null;
}

export interface StrategyRuntimeInfo {
  strategy_account_id: string;
  runtime_id?: string | null;
  status: string;
  execution_mode: string;
  trading_enabled: boolean;
  strategy_code: string;
  exchange: string;
  exchange_account_id: string;
  exchange_account_label: string;
  last_heartbeat_at?: string | null;
  last_error?: string | null;
}

export class PlatformApiClient {
  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const url = `/api/proxy${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;
    const response = await fetch(url, {
      ...options,
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        ...(options.headers as Record<string, string>),
      },
      cache: "no-store",
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Platform API error ${response.status}`);
    }
    return response.json();
  }

  async syncUser(payload: {
    email: string;
    google_id?: string | null;
    name?: string | null;
    avatar_url?: string | null;
  }): Promise<PlatformUser> {
    return this.request("/api/v1/platform/me/sync", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async getMe(): Promise<PlatformUser> {
    return this.request("/api/v1/platform/me");
  }

  async listStrategies(): Promise<{ connected: boolean; strategies: PlatformStrategy[] }> {
    return this.request("/api/v1/platform/strategies");
  }

  async getStrategy(code: string): Promise<PlatformStrategy> {
    return this.request(`/api/v1/platform/strategies/${code}`);
  }

  async listSubscriptions(): Promise<{ connected: boolean; subscriptions: any[] }> {
    return this.request("/api/v1/platform/subscriptions");
  }

  async subscribe(strategyCode: string): Promise<any> {
    return this.request("/api/v1/platform/subscriptions", {
      method: "POST",
      body: JSON.stringify({ strategy_code: strategyCode }),
    });
  }

  async linkStrategyAccount(
    subscriptionId: string,
    payload: {
      exchange_account_id: string;
      execution_mode?: "PAPER" | "LIVE" | "LIVE_DRY_RUN";
      allocation_pct?: number;
      risk_overrides?: Record<string, unknown>;
      confirm_live?: boolean;
      status?: string;
    },
  ): Promise<any> {
    return this.request(`/api/v1/platform/subscriptions/${subscriptionId}/accounts`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async getAccountStrategies(accountId: string): Promise<{ connected: boolean; strategies: any[] }> {
    return this.request(`/api/v1/platform/accounts/${accountId}/strategies`);
  }

  async getStrategyAccount(strategyAccountId: string): Promise<any> {
    return this.request(`/api/v1/platform/strategy-accounts/${strategyAccountId}`);
  }

  async getPortfolioPerformance(params?: {
    range?: EquityRange;
    strategy?: string;
    account_id?: string;
  }): Promise<any> {
    const q = new URLSearchParams();
    if (params?.range) q.set("range", params.range);
    if (params?.strategy) q.set("strategy", params.strategy);
    if (params?.account_id) q.set("account_id", params.account_id);
    const suffix = q.toString() ? `?${q.toString()}` : "";
    return this.request(`/api/v1/platform/portfolio/performance${suffix}`);
  }

  async getPlatformTrades(params?: {
    strategy?: string;
    strategy_account_id?: string;
    account_id?: string;
    status?: string;
    from?: string;
    to?: string;
    limit?: number;
  }): Promise<{ connected: boolean; user_scoped: boolean; count: number; trades: PlatformTrade[] }> {
    const q = new URLSearchParams();
    if (params?.strategy) q.set("strategy", params.strategy);
    if (params?.strategy_account_id) q.set("strategy_account_id", params.strategy_account_id);
    if (params?.account_id) q.set("account_id", params.account_id);
    if (params?.status) q.set("status", params.status);
    if (params?.from) q.set("from", params.from);
    if (params?.to) q.set("to", params.to);
    if (params?.limit) q.set("limit", String(params.limit));
    const suffix = q.toString() ? `?${q.toString()}` : "";
    return this.request(`/api/v1/platform/trades${suffix}`);
  }

  async getPlatformPerformance(params?: {
    strategy?: string;
    account_id?: string;
    from?: string;
    to?: string;
  }): Promise<any> {
    const q = new URLSearchParams();
    if (params?.strategy) q.set("strategy", params.strategy);
    if (params?.account_id) q.set("account_id", params.account_id);
    if (params?.from) q.set("from", params.from);
    if (params?.to) q.set("to", params.to);
    const suffix = q.toString() ? `?${q.toString()}` : "";
    return this.request(`/api/v1/platform/performance${suffix}`);
  }

  async listAccounts(): Promise<{ connected: boolean; accounts: PlatformExchangeAccount[] }> {
    return this.request("/api/v1/platform/accounts");
  }

  async getAccount(accountId: string): Promise<PlatformExchangeAccount> {
    return this.request(`/api/v1/platform/accounts/${accountId}`);
  }

  async getAccountDetail(accountId: string): Promise<AccountDetailResponse> {
    return this.request(`/api/v1/platform/accounts/${accountId}/detail`);
  }

  async getEquityCurve(accountId: string, range: EquityRange = "1M"): Promise<{
    account_id: string;
    currency: string;
    range: string;
    points: EquityCurvePoint[];
  }> {
    return this.request(`/api/v1/platform/accounts/${accountId}/equity?range=${range}`);
  }

  async testConnection(payload: {
    exchange: string;
    label: string;
    api_key: string;
    api_secret: string;
    passphrase?: string;
    is_testnet?: boolean;
  }): Promise<{ success: boolean; message: string }> {
    return this.request("/api/v1/platform/accounts/test-connection", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async connectAccount(payload: {
    exchange: string;
    label: string;
    api_key: string;
    api_secret: string;
    passphrase?: string;
    is_testnet?: boolean;
  }): Promise<PlatformExchangeAccount> {
    return this.request("/api/v1/platform/accounts", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async syncAccount(accountId: string): Promise<PlatformExchangeAccount> {
    return this.request(`/api/v1/platform/accounts/${accountId}/sync`, {
      method: "POST",
    });
  }

  async getSupportedExchanges(): Promise<{ exchanges: any[] }> {
    return this.request("/api/v1/platform/exchanges/supported");
  }

  async getDashboardSummary(): Promise<DashboardSummary> {
    return this.request("/api/v1/platform/dashboard/summary");
  }

  async getStrategyPerformance(code: string, range: EquityRange = "1M"): Promise<any> {
    return this.request(`/api/v1/platform/strategies/${code}/performance?range=${range}`);
  }

  async listStrategyRuntimes(): Promise<{ connected: boolean; runtimes: StrategyRuntimeInfo[] }> {
    return this.request("/api/v1/platform/strategy-accounts/runtimes");
  }

  async startStrategyRuntime(strategyAccountId: string): Promise<StrategyRuntimeInfo> {
    return this.request(`/api/v1/platform/strategy-accounts/${strategyAccountId}/start`, { method: "POST" });
  }

  async stopStrategyRuntime(strategyAccountId: string): Promise<StrategyRuntimeInfo> {
    return this.request(`/api/v1/platform/strategy-accounts/${strategyAccountId}/stop`, { method: "POST" });
  }

  async pauseStrategyRuntime(strategyAccountId: string): Promise<StrategyRuntimeInfo> {
    return this.request(`/api/v1/platform/strategy-accounts/${strategyAccountId}/pause`, { method: "POST" });
  }

  async resumeStrategyRuntime(strategyAccountId: string): Promise<StrategyRuntimeInfo> {
    return this.request(`/api/v1/platform/strategy-accounts/${strategyAccountId}/resume`, { method: "POST" });
  }

  async enableStrategyTrading(strategyAccountId: string, confirmLive = false): Promise<any> {
    return this.request(`/api/v1/platform/strategy-accounts/${strategyAccountId}/enable-trading`, {
      method: "POST",
      body: JSON.stringify({ confirm_live: confirmLive }),
    });
  }

  async disableStrategyTrading(strategyAccountId: string): Promise<any> {
    return this.request(`/api/v1/platform/strategy-accounts/${strategyAccountId}/disable-trading`, {
      method: "POST",
    });
  }

  async setStrategyExecutionMode(
    strategyAccountId: string,
    mode: "PAPER" | "LIVE" | "LIVE_DRY_RUN",
    confirmLive = false,
  ): Promise<any> {
    return this.request(`/api/v1/platform/strategy-accounts/${strategyAccountId}/execution-mode`, {
      method: "POST",
      body: JSON.stringify({ mode, confirm_live: confirmLive }),
    });
  }

  async recoverStrategyRuntime(strategyAccountId: string): Promise<any> {
    return this.request(`/api/v1/platform/strategy-accounts/${strategyAccountId}/recover`, {
      method: "POST",
    });
  }

  async getValidationReport(strategyAccountId: string): Promise<any> {
    return this.request(`/api/v1/platform/strategy-accounts/${strategyAccountId}/validation`);
  }

  async getExecutionHistory(strategyAccountId: string, status?: string): Promise<any> {
    const q = status ? `?status=${encodeURIComponent(status)}` : "";
    return this.request(`/api/v1/platform/strategy-accounts/${strategyAccountId}/execution-history${q}`);
  }

  getEventsStreamUrl(): string {
    return "/api/proxy/api/v1/platform/events/stream";
  }
}

export const platformApi = new PlatformApiClient();

export { apiClient };
