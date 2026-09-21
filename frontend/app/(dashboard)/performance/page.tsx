"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { LineChart } from "lucide-react";
import { PageHeader, EmptyState } from "@/components/ui/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { EquityCurveChart } from "@/components/charts/equity-curve-chart";
import { PnlCharts } from "@/components/dashboard/pnl-charts";
import { PerformanceOverview } from "@/components/dashboard/performance-overview";
import { usePlatformPortfolioPerformance, usePlatformSubscriptions } from "@/hooks/usePlatform";
import { usePerformanceMetrics } from "@/hooks/usePerformanceMetrics";
import type { EquityRange } from "@/lib/api/platform-client";
import { ENGINE_STRATEGIES, type EngineStrategySlug } from "@/lib/engine-strategies";
import { cn, formatCurrency, formatPercent } from "@/lib/utils";

export default function PerformancePage() {
  const [range, setRange] = useState<EquityRange>("1M");
  const [strategyFilter, setStrategyFilter] = useState("");
  const [engineSlug, setEngineSlug] = useState<EngineStrategySlug>("eth");
  const engine = ENGINE_STRATEGIES.find((s) => s.slug === engineSlug)!;
  const engineMetrics = usePerformanceMetrics({ strategy_name: engine.code });

  const { data: subsData } = usePlatformSubscriptions();
  const { data, isLoading, isError } = usePlatformPortfolioPerformance({
    range,
    strategy: strategyFilter || undefined,
  });

  const subscribedCodes = useMemo(() => {
    const codes = new Set<string>();
    for (const sub of subsData?.subscriptions ?? []) {
      if (sub.strategy?.code) codes.add(sub.strategy.code);
    }
    return Array.from(codes);
  }, [subsData]);

  const combined = data?.combined;
  const combinedMetrics = combined?.curve_metrics;
  const combinedRealized = combined?.realized;
  const strategies = data?.strategies ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Performance"
        description="Live engine P&L per strategy, then platform account equity from synced exchanges."
        icon={LineChart}
      />

      <div className="space-y-3">
        <div className="flex flex-wrap gap-2">
          {ENGINE_STRATEGIES.map((s) => (
            <button
              key={s.slug}
              type="button"
              onClick={() => setEngineSlug(s.slug)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-semibold border",
                engineSlug === s.slug
                  ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                  : "text-muted-foreground border-border/60 hover:bg-secondary/50"
              )}
            >
              {s.shortLabel}
            </button>
          ))}
        </div>
        <PerformanceOverview
          metrics={engineMetrics.metrics}
          isLoading={engineMetrics.isLoading}
          title={`${engine.label} (engine)`}
        />
        <PnlCharts
          title={`${engine.label} equity curve`}
          metrics={engineMetrics.metrics}
          isLoading={engineMetrics.isLoading}
        />
      </div>

      <div className="border-t border-border/60 pt-6 space-y-4">
        <p className="text-xs uppercase tracking-wider text-muted-foreground">Platform accounts</p>
        <div className="flex flex-wrap items-center gap-3">
          <div className="space-y-1">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Strategy filter</p>
            <Select
              className="w-52"
              value={strategyFilter}
              onChange={(e) => setStrategyFilter(e.target.value)}
            >
              <option value="">All Strategies</option>
              {subscribedCodes.map((code) => (
                <option key={code} value={code}>
                  {code}
                </option>
              ))}
            </Select>
          </div>
        </div>

        {isLoading && <Skeleton className="h-72 w-full rounded-xl" />}
        {isError && (
          <EmptyState
            title="Unable to load portfolio performance"
            description="Ensure platform database and account sync are available."
          />
        )}

        {!isLoading && !isError && (
          <>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
              <MetricCard label="Total Equity (accounts)" value={formatCurrency(combined?.total_equity ?? 0)} />
              <MetricCard
                label="Unrealized P&L"
                value={
                  combined?.total_unrealized_pnl != null
                    ? formatCurrency(combined.total_unrealized_pnl)
                    : "Not available yet"
                }
                tone={(combined?.total_unrealized_pnl ?? 0) >= 0 ? "positive" : "negative"}
              />
              <MetricCard
                label="Realized P&L (attributed)"
                value={
                  combinedRealized?.available
                    ? formatCurrency(combinedRealized.realized_pnl ?? 0)
                    : "Not available yet"
                }
                tone={(combinedRealized?.realized_pnl ?? 0) >= 0 ? "positive" : "negative"}
              />
              <MetricCard
                label="Period Return"
                value={
                  combinedMetrics?.available && combinedMetrics.return_pct != null
                    ? formatPercent(combinedMetrics.return_pct)
                    : "Not available yet"
                }
              />
              <MetricCard
                label="Max Drawdown"
                value={
                  combinedMetrics?.available && combinedMetrics.max_drawdown_pct != null
                    ? formatPercent(combinedMetrics.max_drawdown_pct)
                    : "Not available yet"
                }
              />
            </div>

            <EquityCurveChart
              title="Account Equity Curve (combined)"
              currency="USD"
              points={combined?.equity_curve ?? []}
              range={range}
              onRangeChange={setRange}
              isLoading={isLoading}
            />

            {strategies.length > 0 && (
              <div className="grid gap-3">
                {strategies.map((row: any) => (
                  <Card key={row.strategy_account_id} className="bg-card/50 border-border/70">
                    <CardContent className="p-4 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                      <div>
                        <div className="flex items-center gap-2 flex-wrap">
                          <p className="font-medium">{row.strategy_name}</p>
                          <Badge variant="outline" className="text-[10px]">
                            {row.strategy_code}
                          </Badge>
                        </div>
                      </div>
                      <Link
                        href={`/execution/${row.strategy_account_id}`}
                        className="text-[10px] text-emerald-400 hover:underline"
                      >
                        View runtime
                      </Link>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "positive" | "negative";
}) {
  return (
    <Card className="bg-card/60 border-border/70">
      <CardContent className="p-4">
        <p className="text-[10px] uppercase text-muted-foreground">{label}</p>
        <p
          className={cn(
            "text-lg font-mono font-semibold mt-1",
            tone === "positive" && "text-emerald-400",
            tone === "negative" && "text-rose-400"
          )}
        >
          {value}
        </p>
      </CardContent>
    </Card>
  );
}
