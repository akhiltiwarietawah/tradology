"use client";

import React from "react";
import {
  TrendingUp,
  TrendingDown,
  Percent,
  Activity,
  DollarSign,
  Shield,
  Layers,
  Award,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import type { PerformanceMetricsResponse } from "@/lib/api/schemas";

interface PerformanceOverviewProps {
  metrics?: PerformanceMetricsResponse | null;
  isLoading?: boolean;
}

export function PerformanceOverview({ metrics, isLoading }: PerformanceOverviewProps) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        {Array.from({ length: 7 }).map((_, i) => (
          <Card key={i} className="bg-card/40 border-border/60">
            <CardContent className="p-4 space-y-2">
              <Skeleton className="h-3 w-16" />
              <Skeleton className="h-6 w-24" />
              <Skeleton className="h-3 w-12" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  const netPnl = metrics?.net_pnl ?? 0;
  const realizedPnl = metrics?.total_realized_pnl ?? 0;
  const fees = metrics?.total_fees ?? 0;
  const winRate = metrics?.win_rate ?? 0;
  const profitFactor = metrics?.profit_factor ?? 0;
  const maxDdAmount = metrics?.max_drawdown_amount ?? 0;
  const maxDdPct = metrics?.max_drawdown_pct ?? 0;
  const totalTrades = metrics?.total_trades ?? 0;
  const wins = metrics?.winning_trades ?? 0;
  const losses = metrics?.losing_trades ?? 0;

  // Latest daily P&L point (today's P&L)
  const todayEntry = metrics?.daily_pnl && metrics.daily_pnl.length > 0
    ? metrics.daily_pnl[metrics.daily_pnl.length - 1]
    : null;
  const todayNetPnl = todayEntry ? todayEntry.net_pnl : 0;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
      {/* 1. Today's P&L */}
      <Card className="bg-card/60 border-border/80 hover:border-border transition-colors">
        <CardContent className="p-3.5 flex flex-col justify-between h-full">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-[11px] font-semibold uppercase tracking-wider">Today&apos;s Net P&amp;L</span>
            {todayNetPnl >= 0 ? (
              <TrendingUp className="h-3.5 w-3.5 text-emerald-400" />
            ) : (
              <TrendingDown className="h-3.5 w-3.5 text-rose-400" />
            )}
          </div>
          <div className="my-1">
            <div className={`text-lg font-bold font-mono tracking-tight ${todayNetPnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
              {formatCurrency(todayNetPnl)}
            </div>
          </div>
          <div className="text-[10px] text-muted-foreground font-mono">
            {todayEntry ? `${todayEntry.trades_count} trade${todayEntry.trades_count === 1 ? "" : "s"} today` : "No trades today"}
          </div>
        </CardContent>
      </Card>

      {/* 2. Cumulative Net P&L */}
      <Card className="bg-card/60 border-border/80 hover:border-border transition-colors">
        <CardContent className="p-3.5 flex flex-col justify-between h-full">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-[11px] font-semibold uppercase tracking-wider">Total Net P&amp;L</span>
            <DollarSign className="h-3.5 w-3.5 text-blue-400" />
          </div>
          <div className="my-1">
            <div className={`text-lg font-bold font-mono tracking-tight ${netPnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
              {formatCurrency(netPnl)}
            </div>
          </div>
          <div className="text-[10px] text-muted-foreground font-mono">
            Gross: {formatCurrency(realizedPnl)}
          </div>
        </CardContent>
      </Card>

      {/* 3. Win Rate */}
      <Card className="bg-card/60 border-border/80 hover:border-border transition-colors">
        <CardContent className="p-3.5 flex flex-col justify-between h-full">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-[11px] font-semibold uppercase tracking-wider">Win Rate</span>
            <Percent className="h-3.5 w-3.5 text-emerald-400" />
          </div>
          <div className="my-1">
            <div className="text-lg font-bold font-mono tracking-tight text-foreground">
              {formatPercent(winRate, 1).replace("+", "")}
            </div>
          </div>
          <div className="text-[10px] text-muted-foreground font-mono">
            <span className="text-emerald-400">{wins}W</span> / <span className="text-rose-400">{losses}L</span>
          </div>
        </CardContent>
      </Card>

      {/* 4. Profit Factor */}
      <Card className="bg-card/60 border-border/80 hover:border-border transition-colors">
        <CardContent className="p-3.5 flex flex-col justify-between h-full">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-[11px] font-semibold uppercase tracking-wider">Profit Factor</span>
            <Award className="h-3.5 w-3.5 text-amber-400" />
          </div>
          <div className="my-1">
            <div className="text-lg font-bold font-mono tracking-tight text-foreground">
              {profitFactor > 0 ? formatNumber(profitFactor, 2) : "--"}
            </div>
          </div>
          <div className="text-[10px] text-muted-foreground font-mono">
            Payoff: {metrics?.payoff_ratio ? formatNumber(metrics.payoff_ratio, 2) : "--"}
          </div>
        </CardContent>
      </Card>

      {/* 5. Max Drawdown */}
      <Card className="bg-card/60 border-border/80 hover:border-border transition-colors">
        <CardContent className="p-3.5 flex flex-col justify-between h-full">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-[11px] font-semibold uppercase tracking-wider">Max Drawdown</span>
            <Shield className="h-3.5 w-3.5 text-rose-400" />
          </div>
          <div className="my-1">
            <div className="text-lg font-bold font-mono tracking-tight text-rose-400">
              {maxDdAmount > 0 ? `-${formatCurrency(maxDdAmount)}` : "$0.00"}
            </div>
          </div>
          <div className="text-[10px] text-muted-foreground font-mono">
            Peak DD: {maxDdPct > 0 ? `-${maxDdPct.toFixed(1)}%` : "0.0%"}
          </div>
        </CardContent>
      </Card>

      {/* 6. Total Fees */}
      <Card className="bg-card/60 border-border/80 hover:border-border transition-colors">
        <CardContent className="p-3.5 flex flex-col justify-between h-full">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-[11px] font-semibold uppercase tracking-wider">Total Fees</span>
            <Activity className="h-3.5 w-3.5 text-muted-foreground" />
          </div>
          <div className="my-1">
            <div className="text-lg font-bold font-mono tracking-tight text-foreground">
              {formatCurrency(fees)}
            </div>
          </div>
          <div className="text-[10px] text-muted-foreground font-mono">
            Exchange + Brokerage
          </div>
        </CardContent>
      </Card>

      {/* 7. Total Trades */}
      <Card className="bg-card/60 border-border/80 hover:border-border transition-colors col-span-2 md:col-span-1">
        <CardContent className="p-3.5 flex flex-col justify-between h-full">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-[11px] font-semibold uppercase tracking-wider">Total Trades</span>
            <Layers className="h-3.5 w-3.5 text-purple-400" />
          </div>
          <div className="my-1">
            <div className="text-lg font-bold font-mono tracking-tight text-foreground">
              {totalTrades}
            </div>
          </div>
          <div className="text-[10px] text-muted-foreground font-mono">
            Streak: {metrics?.current_streak ?? 0} ({metrics?.max_consecutive_wins ?? 0} max W)
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
