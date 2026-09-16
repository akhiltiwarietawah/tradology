"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { RefreshCw, TrendingUp, Wallet, Zap } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/page-header";
import { EquityCurveChart } from "@/components/charts/equity-curve-chart";
import {
  usePlatformAccounts,
  usePlatformDashboardSummary,
  useSyncExchangeAccount,
} from "@/hooks/usePlatform";
import {
  formatCurrency,
  formatPercent,
  formatRelativeTime,
  healthBadgeVariant,
} from "@/lib/utils";
import type { EquityRange } from "@/lib/api/platform-client";
import { platformApi } from "@/lib/api/platform-client";

function computeTodayPnl(points: { timestamp: string; equity: number }[]): number | null {
  if (points.length < 2) return null;
  const today = new Date().toDateString();
  const todayPoints = points.filter((p) => new Date(p.timestamp).toDateString() === today);
  if (todayPoints.length >= 2) {
    return todayPoints[todayPoints.length - 1].equity - todayPoints[0].equity;
  }
  return points[points.length - 1].equity - points[0].equity;
}

export function PlatformPortfolioSection() {
  const { data: summary, isLoading } = usePlatformDashboardSummary();
  const { data: accountsData } = usePlatformAccounts();
  const syncAccount = useSyncExchangeAccount();
  const [equityRange, setEquityRange] = useState<EquityRange>("1M");

  const accounts = summary?.accounts ?? accountsData?.accounts ?? [];
  const hasAccounts = accounts.length > 0;

  const equityQueries = useQueries({
    queries: accounts.map((account) => ({
      queryKey: ["platformEquityCurve", account.id, equityRange],
      queryFn: () => platformApi.getEquityCurve(account.id, equityRange),
      enabled: !!account.id,
      staleTime: 30000,
    })),
  });

  const aggregatedCurve = useMemo(() => {
    const byTime = new Map<string, number>();
    for (const query of equityQueries) {
      for (const point of query.data?.points ?? []) {
        byTime.set(point.timestamp, (byTime.get(point.timestamp) || 0) + point.equity);
      }
    }
    return Array.from(byTime.entries())
      .map(([timestamp, equity]) => ({ timestamp, equity }))
      .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
  }, [equityQueries]);

  const todayPnl = useMemo(() => computeTodayPnl(aggregatedCurve), [aggregatedCurve]);
  const equityLoading = equityQueries.some((q) => q.isLoading);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-lg" />
          ))}
        </div>
        <Skeleton className="h-72 rounded-lg" />
      </div>
    );
  }

  if (!hasAccounts) {
    return (
      <EmptyState
        title="Connect an exchange to track portfolio equity"
        description="Link Binance, Bybit, OKX, or Delta India to sync balances, positions, and equity curves in real time."
        action={
          <Link href="/connect">
            <Button size="sm">Connect Exchange</Button>
          </Link>
        }
      />
    );
  }

  const totalEquity = summary?.total_equity ?? 0;
  const totalUnrealized = summary?.total_unrealized_pnl ?? 0;
  const activeStrategies = summary?.active_subscriptions_count ?? 0;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-emerald-300/90">Portfolio</h2>
          <p className="text-[11px] text-muted-foreground mt-0.5">Live data from connected exchange accounts</p>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        {[
          { label: "Total Equity", value: formatCurrency(totalEquity), icon: Wallet },
          {
            label: "Today's P&L",
            value: todayPnl === null ? "--" : formatCurrency(todayPnl),
            tone: todayPnl !== null && todayPnl >= 0 ? "text-emerald-400" : "text-rose-400",
            icon: TrendingUp,
          },
          {
            label: "Unrealized P&L",
            value: formatCurrency(totalUnrealized),
            tone: totalUnrealized >= 0 ? "text-emerald-400" : "text-rose-400",
            icon: TrendingUp,
          },
          { label: "Connected Accounts", value: String(accounts.length), icon: Wallet },
          { label: "Active Strategies", value: String(activeStrategies), icon: Zap },
        ].map(({ label, value, tone, icon: Icon }) => (
          <Card key={label} className="bg-card/60 border-border/70">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p>
                <Icon className="h-3.5 w-3.5 text-muted-foreground/70" />
              </div>
              <p className={`text-lg font-mono font-semibold mt-2 ${tone || ""}`}>{value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <EquityCurveChart
        title="Portfolio Equity"
        currency="USDT"
        points={aggregatedCurve}
        range={equityRange}
        onRangeChange={setEquityRange}
        isLoading={equityLoading}
      />

      <div className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Connected Accounts</h3>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {accounts.map((account) => {
            const equity = account.equity ?? account.balance ?? 0;
            const pct =
              equity > 0 && account.unrealized_pnl
                ? (account.unrealized_pnl / equity) * 100
                : null;
            const health = account.health_status || account.status || account.connection_status;

            return (
              <Card key={account.id} className="bg-card/60 border-border/70 hover:border-emerald-500/20 transition-colors">
                <CardContent className="p-4 space-y-3">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <Link href={`/accounts/${account.id}`} className="font-semibold hover:text-emerald-300 transition-colors">
                        {account.label}
                      </Link>
                      <p className="text-[10px] uppercase text-muted-foreground mt-0.5">{account.exchange}</p>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 w-7 p-0"
                      disabled={syncAccount.isPending}
                      onClick={() => syncAccount.mutate(account.id)}
                    >
                      <RefreshCw className={`h-3 w-3 ${syncAccount.isPending ? "animate-spin" : ""}`} />
                    </Button>
                  </div>
                  <div className="flex items-end justify-between">
                    <div>
                      <p className="text-xl font-mono font-semibold">{formatCurrency(equity)}</p>
                      {pct !== null && (
                        <p className={`text-xs font-mono mt-0.5 ${pct >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                          {formatPercent(pct)}
                        </p>
                      )}
                    </div>
                    <Badge variant={healthBadgeVariant(health)} className="text-[10px]">
                      {health}
                    </Badge>
                  </div>
                  <p className="text-[10px] text-muted-foreground font-mono">
                    Last synced {formatRelativeTime(account.last_synced_at || account.last_sync_at)}
                  </p>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>

      {(summary?.subscriptions?.length ?? 0) > 0 && (
        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Active Strategies</h3>
          <div className="grid gap-3 md:grid-cols-2">
            {summary!.subscriptions.slice(0, 6).map((sub) => (
              <Card key={sub.id} className="bg-card/60 border-border/70">
                <CardContent className="p-4 flex items-center justify-between">
                  <div>
                    <p className="font-medium text-sm">{sub.strategy?.name || "Strategy"}</p>
                    <p className="text-[10px] text-muted-foreground mt-0.5">{sub.strategy?.code}</p>
                  </div>
                  <Badge variant={sub.status === "ACTIVE" ? "success" : "secondary"}>{sub.status}</Badge>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
