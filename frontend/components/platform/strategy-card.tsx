"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, TrendingDown, TrendingUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { platformApi, type PlatformStrategy } from "@/lib/api/platform-client";
import { cn, formatCurrency, formatPercent } from "@/lib/utils";

interface StrategyCardProps {
  strategy: PlatformStrategy;
  subscribed?: boolean;
}

export function StrategyCard({ strategy, subscribed }: StrategyCardProps) {
  const { data: performance, isLoading } = useQuery({
    queryKey: ["platformStrategyPerformance", strategy.code],
    queryFn: () => platformApi.getStrategyPerformance(strategy.code),
    staleTime: 60000,
  });

  const summary = performance?.summary || {};
  const hasMetrics = Boolean(summary && (summary.total_trades || summary.net_pnl != null));
  const pnl = Number(summary.net_pnl ?? summary.total_pnl ?? 0);
  const winRate = summary.win_rate != null ? Number(summary.win_rate) : null;
  const maxDd = summary.max_drawdown_pct != null ? Number(summary.max_drawdown_pct) : null;

  return (
    <Card className="group bg-card/50 border-border/70 hover:border-emerald-500/25 hover:bg-card/70 transition-all duration-200">
      <CardContent className="p-5 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-semibold tracking-tight">{strategy.name}</h3>
              {subscribed && (
                <Badge variant="success" className="text-[10px]">
                  Subscribed
                </Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-1.5 line-clamp-2 leading-relaxed">
              {strategy.description || "Algorithmic strategy available on Tradology."}
            </p>
          </div>
          <Badge variant="outline" className="text-[10px] shrink-0 font-mono">
            {strategy.timeframe || "MULTI"}
          </Badge>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {(strategy.markets || []).slice(0, 3).map((m) => (
            <Badge key={m} variant="secondary" className="text-[10px] font-mono">
              {m}
            </Badge>
          ))}
          {(strategy.supported_exchanges || []).slice(0, 2).map((ex) => (
            <Badge key={ex} variant="outline" className="text-[10px]">
              {ex}
            </Badge>
          ))}
        </div>

        <div className="grid grid-cols-3 gap-2 pt-1">
          <MetricCell
            label="Benchmark P&L"
            loading={isLoading}
            value={hasMetrics ? formatCurrency(pnl) : "N/A"}
            tone={pnl >= 0 ? "positive" : "negative"}
          />
          <MetricCell
            label="Win rate"
            loading={isLoading}
            value={winRate != null ? formatPercent(winRate) : "N/A"}
          />
          <MetricCell
            label="Max DD"
            loading={isLoading}
            value={maxDd != null ? formatPercent(maxDd) : "N/A"}
            tone="muted"
          />
        </div>

        {!hasMetrics && !isLoading && (
          <p className="text-[10px] text-muted-foreground border-t border-border/40 pt-3">
            Performance benchmark not available yet — strategy metadata only.
          </p>
        )}
        {hasMetrics && (
          <p className="text-[10px] text-muted-foreground">Global engine benchmark — not personal P&L</p>
        )}

        <div className="flex items-center justify-between pt-2 border-t border-border/50">
          <span className="text-[11px] text-muted-foreground">Risk: {strategy.risk_profile || "—"}</span>
          <div className="flex items-center gap-2">
            <Link href={`/strategies/${strategy.code}`} className={cn(buttonVariants({ size: "sm", variant: "ghost" }), "h-8 text-xs")}>
              View
            </Link>
            <Link
              href={subscribed ? "/my-strategies" : `/strategies/${strategy.code}/subscribe`}
              className={cn(buttonVariants({ size: "sm" }), "h-8 text-xs gap-1")}
            >
              {subscribed ? "Manage" : "Subscribe"}
              <ArrowRight className="h-3 w-3" />
            </Link>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function MetricCell({
  label,
  value,
  loading,
  tone,
}: {
  label: string;
  value: string;
  loading?: boolean;
  tone?: "positive" | "negative" | "muted";
}) {
  return (
    <div className="rounded-md border border-border/50 bg-background/30 px-2.5 py-2">
      <p className="text-[9px] uppercase tracking-wider text-muted-foreground">{label}</p>
      {loading ? (
        <div className="h-4 mt-1 rounded bg-secondary/60 animate-pulse" />
      ) : (
        <p
          className={cn(
            "text-xs font-mono font-semibold mt-0.5 flex items-center gap-0.5",
            tone === "positive" && "text-emerald-400",
            tone === "negative" && "text-rose-400",
            tone === "muted" && "text-muted-foreground",
          )}
        >
          {tone === "positive" && <TrendingUp className="h-3 w-3" />}
          {tone === "negative" && <TrendingDown className="h-3 w-3" />}
          {value}
        </p>
      )}
    </div>
  );
}
