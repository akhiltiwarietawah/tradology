"use client";

import React from "react";
import { RefreshCw } from "lucide-react";
import { useSystemStatus } from "@/hooks/useSystemStatus";
import { ApiErrorBanner } from "@/components/ui/api-error-banner";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { EngineStatusBar } from "@/components/dashboard/engine-status-bar";
import { StrategySummaryCardLoader } from "@/components/dashboard/strategy-summary-card-loader";
import { SystemHealth } from "@/components/dashboard/system-health";
import { RiskSafety } from "@/components/dashboard/risk-safety";
import { PlatformPortfolioSection } from "@/components/platform/platform-portfolio";
import { liveEngineStrategies } from "@/lib/renko-status";

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

  const handleRefreshAll = () => {
    refetchStatus();
  };

  const strangleOpen = !!(
    statusData?.current_trade?.trade_id &&
    statusData.current_trade.trade_state !== "COMPLETED"
  );

  const liveStrategies = liveEngineStrategies(statusData);

  return (
    <div className="space-y-5 pb-10">
      <PageHeader
        title="Overview"
        description="One card per strategy enabled in the engine (.env). OFF coins are hidden here."
        action={
          <Button variant="outline" size="sm" onClick={handleRefreshAll} className="h-8 text-[11px]">
            <RefreshCw className="h-3 w-3 mr-1.5" />
            Refresh
          </Button>
        }
      />

      <PlatformPortfolioSection />

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

      <EngineStatusBar
        status={statusData}
        isSafeHalt={isSafeHalt}
        isRunning={isRunning}
        isExchangeConnected={isExchangeConnected}
        isWsStale={isWsStale}
        isSynchronized={isSynchronized}
        isDbConnected={isDbConnected}
      />

      <div>
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          Strategy pages
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {liveStrategies.map((strategy) => (
            <StrategySummaryCardLoader
              key={strategy.slug}
              strategy={strategy}
              snapshot={
                strategy.snapshotKey ? statusData?.strategies?.[strategy.snapshotKey] : null
              }
              strangleOpen={strategy.kind === "strangle" ? strangleOpen : undefined}
            />
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        <div className="lg:col-span-5">
          <RiskSafety status={statusData} isLoading={isStatusLoading} />
        </div>
        <div className="lg:col-span-7">
          <SystemHealth status={statusData} isLoading={isStatusLoading} />
        </div>
      </div>
    </div>
  );
}
