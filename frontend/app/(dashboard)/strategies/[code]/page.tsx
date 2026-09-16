"use client";

import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Waypoints } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { platformApi, type EquityRange } from "@/lib/api/platform-client";
import { PageHeader, EmptyState } from "@/components/ui/page-header";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EquityCurveChart } from "@/components/charts/equity-curve-chart";
import { cn, formatCurrency, formatPercent } from "@/lib/utils";
import { usePlatformSubscriptions } from "@/hooks/usePlatform";

export default function StrategyDetailPage() {
  const params = useParams();
  const code = String(params.code || "");
  const [tab, setTab] = useState("overview");
  const [range, setRange] = useState<EquityRange>("1M");
  const { data: subscriptions } = usePlatformSubscriptions();

  const { data: strategy, isLoading, isError } = useQuery({
    queryKey: ["platformStrategy", code],
    queryFn: () => platformApi.getStrategy(code),
    enabled: !!code,
  });

  const { data: performance, isLoading: perfLoading } = useQuery({
    queryKey: ["platformStrategyPerformance", code, range],
    queryFn: () => platformApi.getStrategyPerformance(code, range),
    enabled: !!code,
  });

  const userSubscription = useMemo(
    () => (subscriptions?.subscriptions ?? []).find((s: any) => s.strategy?.code === code),
    [subscriptions, code],
  );

  if (isLoading) return <Skeleton className="h-64 w-full rounded-xl" />;
  if (isError || !strategy) {
    return <EmptyState title="Strategy not found" description={`No strategy with code "${code}" exists.`} />;
  }

  const summary = performance?.summary || {};
  const hasUserMetrics = Boolean(performance?.available && summary.available);
  const strategyAccounts = performance?.strategy_accounts ?? [];
  const curve =
    (performance?.equity_curve ?? []).length > 0
      ? performance.equity_curve.map((p: any) => ({
          timestamp: p.timestamp,
          equity: p.equity ?? 0,
        }))
      : [];

  return (
    <div className="space-y-6">
      <Link href="/strategies" className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "h-8 px-2 text-xs w-fit")}>
        <ArrowLeft className="h-3.5 w-3.5 mr-1" />
        Strategies
      </Link>

      <PageHeader
        title={strategy.name}
        description={strategy.description || "Strategy catalog overview and your subscription performance."}
        icon={Waypoints}
        action={
          userSubscription ? (
            <Link href="/my-strategies" className={cn(buttonVariants({ size: "sm", variant: "outline" }))}>
              Manage Subscription
            </Link>
          ) : (
            <Link href={`/strategies/${strategy.code}/subscribe`} className={cn(buttonVariants({ size: "sm" }))}>
              Subscribe to Strategy
            </Link>
          )
        }
      />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="performance">Performance</TabsTrigger>
          <TabsTrigger value="risk">Risk</TabsTrigger>
          <TabsTrigger value="how">How it works</TabsTrigger>
          <TabsTrigger value="requirements">Requirements</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <div className="grid gap-4 md:grid-cols-4">
            {[
              ["Realized P&L", hasUserMetrics ? formatCurrency(summary.realized_pnl ?? 0) : "Not available yet"],
              ["Win Rate", summary.win_rate != null ? formatPercent(summary.win_rate) : "Not available yet"],
              ["Trades", summary.trade_count != null ? String(summary.trade_count) : "Not available yet"],
              ["Net P&L", hasUserMetrics ? formatCurrency(summary.net_pnl ?? 0) : "Not available yet"],
            ].map(([label, value]) => (
              <Card key={label as string} className="bg-card/60 border-border/70">
                <CardContent className="p-4">
                  <p className="text-[10px] uppercase text-muted-foreground">{label}</p>
                  <p className="text-lg font-mono font-semibold mt-1">{value}</p>
                </CardContent>
              </Card>
            ))}
          </div>
          <p className="text-[10px] text-muted-foreground mt-3">
            Your attributed subscription P&L only. Legacy global benchmark excluded unless no subscription data exists.
          </p>
        </TabsContent>

        <TabsContent value="performance">
          {curve.length > 0 ? (
            <EquityCurveChart
              title="Your Strategy Equity Curve"
              points={curve}
              range={range}
              onRangeChange={setRange}
              isLoading={perfLoading}
            />
          ) : (
            <EmptyState
              title="Not available yet"
              description={
                userSubscription
                  ? "Attributed trades and equity snapshots will appear after platform execution on your linked accounts."
                  : "Subscribe and link an exchange account to track your strategy performance."
              }
            />
          )}
          {strategyAccounts.length > 1 && (
            <p className="text-[10px] text-muted-foreground mt-3">
              {strategyAccounts.length} linked strategy accounts — curves combined chronologically.
            </p>
          )}
        </TabsContent>

        <TabsContent value="risk">
          <Card className="bg-card/60 border-border/70">
            <CardContent className="p-5 space-y-3 text-sm">
              <p>
                <span className="text-muted-foreground">Risk profile:</span> {strategy.risk_profile || "Not specified"}
              </p>
              <p>
                <span className="text-muted-foreground">Timeframe:</span> {strategy.timeframe || "Multi-timeframe"}
              </p>
              <p className="text-xs text-muted-foreground">
                Review strategy-specific parameters during subscription setup. Live execution requires explicit confirmation
                and remains disabled until server operators enable live flags.
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="how">
          <Card className="bg-card/60 border-border/70">
            <CardContent className="p-5 text-sm text-muted-foreground leading-relaxed">
              {strategy.description ||
                "This strategy runs on Tradology with isolated runtime state per exchange account subscription."}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="requirements">
          <Card className="bg-card/60 border-border/70">
            <CardContent className="p-5 space-y-3">
              <p className="text-xs text-muted-foreground uppercase tracking-wider">Supported exchanges</p>
              <div className="flex flex-wrap gap-2">
                {(strategy.supported_exchanges || []).map((ex: string) => (
                  <Badge key={ex} variant="secondary">
                    {ex}
                  </Badge>
                ))}
              </div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider pt-2">Markets</p>
              <div className="flex flex-wrap gap-2">
                {(strategy.markets || []).map((m: string) => (
                  <Badge key={m} variant="outline">
                    {m}
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {!userSubscription && (
        <Card className="bg-emerald-500/5 border-emerald-500/20">
          <CardContent className="p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <p className="font-semibold">Ready to deploy this strategy?</p>
              <p className="text-xs text-muted-foreground mt-1">
                Configure paper or live mode, parameters, and select a connected exchange account.
              </p>
            </div>
            <Link href={`/strategies/${strategy.code}/subscribe`}>
              <Button>Subscribe to Strategy</Button>
            </Link>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
