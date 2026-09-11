"use client";

import React, { useState } from "react";
import {
  Database,
  Lock,
  Radio,
  RefreshCw,
} from "lucide-react";
import { useSystemStatus } from "@/hooks/useSystemStatus";
import { usePerformanceMetrics } from "@/hooks/usePerformanceMetrics";
import { useRenkoTrades } from "@/hooks/useRenkoTrades";
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
  RenkoPanel,
  RenkoTradeHistory,
  StrategyTabs,
  type StrategyTab,
} from "@/components/dashboard";
import { formatDateTime } from "@/lib/utils";

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<StrategyTab>("overview");

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

  const strangleMetrics = usePerformanceMetrics({ strategy_name: "short_strangle" });
  const renkoMetrics = usePerformanceMetrics({ strategy_name: "renko_ichimoku" });

  const {
    trades: renkoTrades,
    openTrade: renkoOpenTrade,
    dbConnected: renkoDbConnected,
    isLoading: isRenkoLoading,
    refetch: refetchRenko,
  } = useRenkoTrades();

  const renkoSnapshot = statusData?.strategies?.renko_ichimoku;
  const renkoEnabled = !!renkoSnapshot?.enabled;

  const showStrangle = activeTab === "overview" || activeTab === "strangle";
  const showRenko = activeTab === "overview" || activeTab === "renko";

  const activeMetrics =
    activeTab === "renko"
      ? renkoMetrics
      : strangleMetrics;

  const handleRefreshAll = () => {
    refetchStatus();
    strangleMetrics.refetch();
    renkoMetrics.refetch();
    refetchRenko();
  };

  const engineStatus = statusData?.engine?.status || "STOPPED";
  const environment = statusData?.engine?.environment || "TESTNET";
  const dryRun = statusData?.engine?.dry_run ?? false;
  const killSwitch = statusData?.engine?.kill_switch ?? false;

  return (
    <div className="space-y-5 pb-10">
      {isStatusError && (
        <ApiErrorBanner
          title={isNetworkError ? "FastAPI Trading Backend Offline" : "API Communication Error"}
          message={
            statusError?.message ||
            "Unable to connect to the trading engine. Real-time updates paused."
          }
          isNetworkError={isNetworkError}
          onRetry={handleRefreshAll}
        />
      )}

      <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-4">
        <StrategyTabs
          activeTab={activeTab}
          onChange={setActiveTab}
          renkoEnabled={renkoEnabled}
        />

        <div className="flex items-center gap-2 self-end xl:self-auto">
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefreshAll}
            className="h-8 text-[11px] px-3 border-border/60"
          >
            <RefreshCw className="h-3 w-3 mr-1.5" />
            Refresh
          </Button>
        </div>
      </div>

      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 bg-card/70 border border-border/80 rounded-lg p-3 px-4 shadow-sm">
        <div className="flex flex-wrap items-center gap-2">
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

          <Badge
            variant={environment === "LIVE" ? "destructive" : "cyan"}
            className="text-[11px] font-mono px-2 py-0.5"
          >
            {environment} • {dryRun ? "DRY RUN" : "LIVE ORDERS"}
          </Badge>

          <Badge variant="outline" className="text-[11px] font-mono border-border/80">
            {activeTab === "renko" ? "RENKO ICHIMOKU" : activeTab === "strangle" ? "BTC STRANGLE" : "MULTI-STRATEGY"}
          </Badge>

          <Badge
            variant={isExchangeConnected ? "success" : "destructive"}
            className="text-[11px] font-mono px-2 py-0.5"
          >
            <Radio className="h-3 w-3 mr-1" />
            DELTA: {isExchangeConnected ? (isWsStale ? "REST FALLBACK" : "CONNECTED") : "OFFLINE"}
          </Badge>

          <Badge variant={isSynchronized ? "success" : "warning"} className="text-[11px] font-mono px-2 py-0.5">
            {isSynchronized ? "SYNCED" : "UNSYNCHRONIZED"}
          </Badge>

          <Badge variant={isDbConnected ? "info" : "secondary"} className="text-[11px] font-mono px-2 py-0.5">
            <Database className="h-3 w-3 mr-1" />
            POSTGRES: {isDbConnected ? "ONLINE" : "FALLBACK"}
          </Badge>

          {killSwitch && (
            <Badge variant="destructive" className="text-[11px] font-mono px-2 py-0.5">
              <Lock className="h-3 w-3 mr-1" />
              KILL SWITCH
            </Badge>
          )}
        </div>

        <div className="text-[11px] font-mono text-muted-foreground">
          Last Sync:{" "}
          {statusData?.reconciliation?.last_reconciliation_time
            ? formatDateTime(statusData.reconciliation.last_reconciliation_time)
            : "--"}
        </div>
      </div>

      <PerformanceOverview
        metrics={activeMetrics.metrics}
        isLoading={activeMetrics.isLoading}
        title={
          activeTab === "renko"
            ? "Renko Performance"
            : activeTab === "strangle"
            ? "Strangle Performance"
            : "Portfolio Performance (Strangle)"
        }
      />

      {showStrangle && (
        <ActiveTrade status={statusData} isLoading={isStatusLoading} />
      )}

      {showRenko && (
        <RenkoPanel snapshot={renkoSnapshot} isLoading={isStatusLoading} />
      )}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        <div className="lg:col-span-5">
          <RiskSafety status={statusData} isLoading={isStatusLoading} />
        </div>
        <div className="lg:col-span-7">
          <PnlCharts
            metrics={activeMetrics.metrics}
            isLoading={activeMetrics.isLoading}
          />
        </div>
      </div>

      {(activeTab === "overview" || activeTab === "strangle") && (
        <TradeHistory
          trades={strangleMetrics.metrics?.cumulative_pnl_curve || []}
          isLoading={strangleMetrics.isLoading}
        />
      )}

      {showRenko && (
        <RenkoTradeHistory
          trades={renkoTrades}
          openTrade={renkoOpenTrade}
          isLoading={isRenkoLoading}
          dbConnected={renkoDbConnected}
        />
      )}

      <SystemHealth status={statusData} isLoading={isStatusLoading} />
    </div>
  );
}
