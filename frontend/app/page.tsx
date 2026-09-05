"use client";

import React from "react";
import {
  Activity,
  ShieldCheck,
  ShieldAlert,
  Server,
  Database,
  Radio,
  Lock,
  RefreshCw,
  Clock,
} from "lucide-react";
import { useSystemStatus } from "@/hooks/useSystemStatus";
import { usePerformanceMetrics } from "@/hooks/usePerformanceMetrics";
import { ApiErrorBanner } from "@/components/ui/api-error-banner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  PerformanceOverview,
  ActiveTrade,
  RiskSafety,
  PnlCharts,
  TradeHistory,
  SystemHealth,
} from "@/components/dashboard";
import { formatDateTime } from "@/lib/utils";

export default function DashboardPage() {
  const {
    statusData,
    isLoading: isStatusLoading,
    isError: isStatusError,
    isNetworkError,
    error: statusError,
    refetch: refetchStatus,
    isSafeHalt,
    isRunning,
    isExchangeConnected,
    isWsStale,
    isSynchronized,
    isDbConnected,
  } = useSystemStatus();

  const {
    metrics,
    isLoading: isMetricsLoading,
    refetch: refetchMetrics,
  } = usePerformanceMetrics();

  const handleRefreshAll = () => {
    refetchStatus();
    refetchMetrics();
  };

  const engineStatus = statusData?.engine?.status || "STOPPED";
  const environment = statusData?.engine?.environment || "TESTNET";
  const dryRun = statusData?.engine?.dry_run ?? false;
  const killSwitch = statusData?.engine?.kill_switch ?? false;

  return (
    <div className="space-y-5 pb-10">
      {/* 1. API Connection / Disconnected Error Banner */}
      {isStatusError && (
        <ApiErrorBanner
          title={isNetworkError ? "FastAPI Trading Backend Offline" : "API Communication Error"}
          message={
            statusError?.message ||
            "Unable to connect to the trading engine on http://localhost:8000. Real-time updates paused."
          }
          isNetworkError={isNetworkError}
          onRetry={handleRefreshAll}
        />
      )}

      {/* 2. Top System Status Bar */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 bg-card/70 border border-border/80 rounded-lg p-3 px-4 shadow-sm">
        <div className="flex flex-wrap items-center gap-2">
          {/* Engine Status Badge */}
          <Badge
            variant={isSafeHalt ? "destructive" : isRunning ? "success" : "secondary"}
            className="text-xs px-2.5 py-1 font-mono font-bold"
          >
            <span
              className={`h-2 w-2 rounded-full mr-1.5 ${
                isSafeHalt
                  ? "bg-rose-400 animate-ping"
                  : isRunning
                  ? "bg-emerald-400 animate-pulse"
                  : "bg-slate-400"
              }`}
            />
            ENGINE {engineStatus}
          </Badge>

          {/* Environment */}
          <Badge
            variant={environment === "LIVE" ? "destructive" : "cyan"}
            className="text-[11px] font-mono px-2 py-0.5"
          >
            {environment} • {dryRun ? "DRY RUN" : "LIVE ORDERS"}
          </Badge>

          {/* Strategy */}
          <Badge variant="outline" className="text-[11px] font-mono border-border/80 text-foreground">
            STRATEGY: {statusData?.engine?.strategy_name?.toUpperCase() || "SHORT_STRANGLE"}
          </Badge>

          {/* Exchange Connection */}
          <Badge
            variant={isExchangeConnected ? "success" : "destructive"}
            className="text-[11px] font-mono px-2 py-0.5"
          >
            <Radio className="h-3 w-3 mr-1" />
            DELTA: {isExchangeConnected ? (isWsStale ? "REST FALLBACK" : "CONNECTED") : "OFFLINE"}
          </Badge>

          {/* Reconciliation */}
          <Badge
            variant={isSynchronized ? "success" : "warning"}
            className="text-[11px] font-mono px-2 py-0.5"
          >
            {isSynchronized ? "SYNCED" : "UNSYNCHRONIZED"}
          </Badge>

          {/* Database */}
          <Badge
            variant={isDbConnected ? "info" : "secondary"}
            className="text-[11px] font-mono px-2 py-0.5"
          >
            <Database className="h-3 w-3 mr-1" />
            POSTGRES: {isDbConnected ? "ONLINE" : "FALLBACK"}
          </Badge>

          {/* Kill Switch */}
          {killSwitch && (
            <Badge variant="destructive" className="text-[11px] font-mono px-2 py-0.5">
              <Lock className="h-3 w-3 mr-1" />
              KILL SWITCH ENGAGED
            </Badge>
          )}
        </div>

        {/* Action / Refresh */}
        <div className="flex items-center gap-3 self-end lg:self-auto">
          <div className="text-[11px] font-mono text-muted-foreground hidden sm:block">
            Last Sync: {statusData?.reconciliation?.last_reconciliation_time ? formatDateTime(statusData.reconciliation.last_reconciliation_time) : "--"}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefreshAll}
            className="h-7 text-[11px] px-2.5 border-border/60 hover:bg-secondary/40"
          >
            <RefreshCw className="h-3 w-3 mr-1.5" />
            Refresh
          </Button>
        </div>
      </div>

      {/* 3. Performance KPI Overview Cards */}
      <PerformanceOverview
        metrics={metrics}
        isLoading={isMetricsLoading}
      />

      {/* 4. Active Trade Monitor (High-visibility position tracking) */}
      <ActiveTrade
        status={statusData}
        isLoading={isStatusLoading}
      />

      {/* 5. Main Middle Grid: Risk/Safety Panel & PnL Analytics */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Risk & Safety Panel (5 Cols) */}
        <div className="lg:col-span-5">
          <RiskSafety
            status={statusData}
            isLoading={isStatusLoading}
          />
        </div>

        {/* P&L & Equity Charts (7 Cols) */}
        <div className="lg:col-span-7">
          <PnlCharts
            metrics={metrics}
            isLoading={isMetricsLoading}
          />
        </div>
      </div>

      {/* 6. Executed Trade History Table */}
      <TradeHistory
        trades={metrics?.cumulative_pnl_curve || []}
        isLoading={isMetricsLoading}
      />

      {/* 7. Connectivity & Watchdog Details */}
      <SystemHealth
        status={statusData}
        isLoading={isStatusLoading}
      />
    </div>
  );
}
