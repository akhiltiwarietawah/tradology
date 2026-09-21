"use client";

import { RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { EngineStatusBar } from "@/components/dashboard/engine-status-bar";
import { PerformanceOverview } from "@/components/dashboard/performance-overview";
import { PnlCharts } from "@/components/dashboard/pnl-charts";
import { RenkoPanel } from "@/components/dashboard/renko-panel";
import { RenkoTradeHistory } from "@/components/dashboard/renko-trade-history";
import { ActiveTrade } from "@/components/dashboard/active-trade";
import { TradeHistory } from "@/components/dashboard/trade-history";
import { useSystemStatus } from "@/hooks/useSystemStatus";
import { usePerformanceMetrics } from "@/hooks/usePerformanceMetrics";
import { useRenkoTrades } from "@/hooks/useRenkoTrades";
import type { EngineStrategyDef } from "@/lib/engine-strategies";

interface StrategyWorkspaceProps {
  strategy: EngineStrategyDef;
}

export function StrategyWorkspace({ strategy }: StrategyWorkspaceProps) {
  const status = useSystemStatus();
  const metrics = usePerformanceMetrics({ strategy_name: strategy.code });
  const renko = useRenkoTrades(80, strategy.code, strategy.kind === "renko");
  const snapshot = strategy.snapshotKey ? status.statusData?.strategies?.[strategy.snapshotKey] : null;

  const handleRefresh = () => {
    status.refetch();
    metrics.refetch();
    if (strategy.kind === "renko") renko.refetch();
  };

  return (
    <div className="space-y-5 pb-10">
      <PageHeader
        title={strategy.label}
        description={
          strategy.kind === "renko"
            ? "Live position, unrealized P&L, equity curve, and this strategy's closed trades only."
            : "BTC short strangle live legs, P&L charts, and this strategy's trade history."
        }
        action={
          <Button variant="outline" size="sm" onClick={handleRefresh} className="h-8 text-[11px]">
            <RefreshCw className="h-3 w-3 mr-1.5" />
            Refresh
          </Button>
        }
      />

      <EngineStatusBar
        status={status.statusData}
        isSafeHalt={status.isSafeHalt}
        isRunning={status.isRunning}
        isExchangeConnected={status.isExchangeConnected}
        isWsStale={status.isWsStale}
        isSynchronized={status.isSynchronized}
        isDbConnected={status.isDbConnected}
      />

      <PerformanceOverview
        metrics={metrics.metrics}
        isLoading={metrics.isLoading}
        title={`${strategy.shortLabel} performance`}
      />

      {strategy.kind === "renko" ? (
        <RenkoPanel snapshot={snapshot} isLoading={status.isLoading} />
      ) : (
        <ActiveTrade status={status.statusData} isLoading={status.isLoading} />
      )}

      <PnlCharts
        title={`${strategy.label} equity & P&L`}
        metrics={metrics.metrics}
        isLoading={metrics.isLoading}
      />

      {strategy.kind === "renko" ? (
        <RenkoTradeHistory
          trades={renko.trades}
          openTrade={renko.openTrade}
          isLoading={renko.isLoading}
          dbConnected={renko.dbConnected}
          title={`${strategy.label} trades`}
        />
      ) : (
        <TradeHistory
          trades={metrics.metrics?.cumulative_pnl_curve || []}
          isLoading={metrics.isLoading}
        />
      )}
    </div>
  );
}
