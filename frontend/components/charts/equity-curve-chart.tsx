"use client";

import React, { useMemo } from "react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatDateTime } from "@/lib/utils";
import type { EquityCurvePoint, EquityRange } from "@/lib/api/platform-client";

interface EquityCurveChartProps {
  title?: string;
  currency?: string;
  points?: EquityCurvePoint[];
  range: EquityRange;
  onRangeChange: (range: EquityRange) => void;
  isLoading?: boolean;
  height?: number;
}

const RANGES: EquityRange[] = ["1D", "1W", "1M", "3M", "ALL"];

function EquityTooltip({ active, payload, currency }: any) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload as EquityCurvePoint & { change?: number };
  return (
    <div className="rounded-md border border-border/70 bg-background/95 px-3 py-2 text-xs shadow-lg">
      <p className="text-muted-foreground font-mono">{formatDateTime(point.timestamp)}</p>
      <p className="font-semibold font-mono mt-1">{formatCurrency(point.equity, currency === "USDT" ? "$" : "$")}</p>
      {typeof point.change === "number" && (
        <p className={`font-mono mt-0.5 ${point.change >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
          {point.change >= 0 ? "+" : ""}
          {point.change.toFixed(2)}
        </p>
      )}
    </div>
  );
}

export function EquityCurveChart({
  title = "Equity Curve",
  currency = "USD",
  points = [],
  range,
  onRangeChange,
  isLoading,
  height = 280,
}: EquityCurveChartProps) {
  const chartData = useMemo(() => {
    if (!points.length) return [];
    const base = points[0]?.equity ?? 0;
    return points.map((p) => ({
      ...p,
      change: p.equity - base,
    }));
  }, [points]);

  const isUp = chartData.length >= 2 && chartData[chartData.length - 1].equity >= chartData[0].equity;

  if (isLoading) {
    return (
      <Card className="bg-card/60 border-border/80">
        <CardHeader className="py-3 px-4 border-b border-border/60">
          <Skeleton className="h-5 w-40" />
        </CardHeader>
        <CardContent className="p-4">
          <Skeleton className={`w-full`} style={{ height }} />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-card/60 border-border/80 shadow-sm">
      <CardHeader className="py-3 px-4 border-b border-border/60 bg-secondary/10">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-xs font-semibold uppercase tracking-wider">{title}</CardTitle>
          <div className="flex items-center gap-1 bg-background/80 p-1 rounded-md border border-border/60">
            {RANGES.map((r) => (
              <Button
                key={r}
                size="sm"
                variant={range === r ? "default" : "ghost"}
                onClick={() => onRangeChange(r)}
                className="text-[11px] h-6 px-2.5"
              >
                {r}
              </Button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-4 pt-5">
        {!chartData.length ? (
          <div
            className="flex items-center justify-center text-xs text-muted-foreground border border-dashed border-border/60 rounded-lg"
            style={{ height }}
          >
            No equity history yet. Sync your account to populate this chart.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={height}>
            <AreaChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={isUp ? "#34d399" : "#f87171"} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={isUp ? "#34d399" : "#f87171"} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
              <XAxis
                dataKey="timestamp"
                tickFormatter={(v) => {
                  const d = new Date(v);
                  return range === "1D"
                    ? d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })
                    : d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
                }}
                tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                minTickGap={24}
              />
              <YAxis
                tickFormatter={(v) => `$${Number(v).toLocaleString()}`}
                tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                width={72}
              />
              <Tooltip content={<EquityTooltip currency={currency} />} />
              <Area
                type="monotone"
                dataKey="equity"
                stroke={isUp ? "#34d399" : "#f87171"}
                strokeWidth={2}
                fill="url(#equityFill)"
                animationDuration={600}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 0 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
