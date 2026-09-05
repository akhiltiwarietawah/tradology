"use client";

import React, { useState } from "react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
  Cell,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { formatCurrency, formatDate } from "@/lib/utils";
import type { PerformanceMetricsResponse } from "@/lib/api/schemas";

interface PnlChartsProps {
  metrics?: PerformanceMetricsResponse | null;
  isLoading?: boolean;
}

export function PnlCharts({ metrics, isLoading }: PnlChartsProps) {
  const [activeTab, setActiveTab] = useState<"cumulative" | "daily" | "monthly">("cumulative");

  if (isLoading) {
    return (
      <Card className="bg-card/60 border-border/80">
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-7 w-48" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-[280px] w-full" />
        </CardContent>
      </Card>
    );
  }

  const cumulativeData = metrics?.cumulative_pnl_curve || [];
  const dailyData = metrics?.daily_pnl || [];
  const monthlyData = metrics?.monthly_pnl || [];

  const hasData =
    (activeTab === "cumulative" && cumulativeData.length > 0) ||
    (activeTab === "daily" && dailyData.length > 0) ||
    (activeTab === "monthly" && monthlyData.length > 0);

  return (
    <Card className="bg-card/60 border-border/80 shadow-sm">
      <CardHeader className="py-3 px-4 border-b border-border/60 bg-secondary/10">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-xs font-semibold text-foreground uppercase tracking-wider">
            P&amp;L &amp; Performance Analytics
          </CardTitle>

          <div className="flex items-center gap-1.5 bg-background/80 p-1 rounded-md border border-border/60">
            <Button
              size="sm"
              variant={activeTab === "cumulative" ? "default" : "ghost"}
              onClick={() => setActiveTab("cumulative")}
              className="text-[11px] h-6 px-2.5"
            >
              Equity Curve
            </Button>
            <Button
              size="sm"
              variant={activeTab === "daily" ? "default" : "ghost"}
              onClick={() => setActiveTab("daily")}
              className="text-[11px] h-6 px-2.5"
            >
              Daily P&amp;L
            </Button>
            <Button
              size="sm"
              variant={activeTab === "monthly" ? "default" : "ghost"}
              onClick={() => setActiveTab("monthly")}
              className="text-[11px] h-6 px-2.5"
            >
              Monthly P&amp;L
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-4 pt-5">
        {!hasData ? (
          <div className="h-[280px] flex flex-col items-center justify-center text-center text-xs text-muted-foreground border border-dashed border-border/60 rounded-md bg-secondary/10 p-6">
            <p className="font-semibold text-foreground">No Historical Trade Analytics Available</p>
            <p className="text-[11px] mt-1 max-w-sm">
              As completed trades are recorded in PostgreSQL or trades.jsonl, the cumulative equity curve and daily breakdown will populate dynamically.
            </p>
          </div>
        ) : (
          <div className="h-[280px] w-full font-mono text-xs">
            {/* 1. Cumulative Equity Curve */}
            {activeTab === "cumulative" && (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={cumulativeData}
                  margin={{ top: 10, right: 10, left: -15, bottom: 0 }}
                >
                  <defs>
                    <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#10b981" stopOpacity={0.35} />
                      <stop offset="95%" stopColor="#10b981" stopOpacity={0.0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.4} />
                  <XAxis
                    dataKey="trade_date"
                    tickFormatter={(val) => formatDate(val)}
                    stroke="#64748b"
                    fontSize={10}
                    tickLine={false}
                  />
                  <YAxis
                    stroke="#64748b"
                    fontSize={10}
                    tickFormatter={(val) => `$${val}`}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#0f172a",
                      borderColor: "#334155",
                      borderRadius: "6px",
                      fontSize: "11px",
                      color: "#f8fafc",
                    }}
                    formatter={(value: any) => [formatCurrency(Number(value)), "Net Cumulative P&L"]}
                    labelFormatter={(label) => `Trade Date: ${label}`}
                  />
                  <ReferenceLine y={0} stroke="#64748b" strokeDasharray="2 2" />
                  <Area
                    type="monotone"
                    dataKey="cumulative_pnl"
                    stroke="#10b981"
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#equityGradient)"
                    isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}

            {/* 2. Daily P&L Bars */}
            {activeTab === "daily" && (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={dailyData}
                  margin={{ top: 10, right: 10, left: -15, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.4} />
                  <XAxis
                    dataKey="date"
                    tickFormatter={(val) => formatDate(val)}
                    stroke="#64748b"
                    fontSize={10}
                    tickLine={false}
                  />
                  <YAxis
                    stroke="#64748b"
                    fontSize={10}
                    tickFormatter={(val) => `$${val}`}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#0f172a",
                      borderColor: "#334155",
                      borderRadius: "6px",
                      fontSize: "11px",
                      color: "#f8fafc",
                    }}
                    formatter={(value: any) => [formatCurrency(Number(value)), "Net Daily P&L"]}
                    labelFormatter={(label) => `Date: ${label}`}
                  />
                  <ReferenceLine y={0} stroke="#64748b" />
                  <Bar dataKey="net_pnl" isAnimationActive={false}>
                    {dailyData.map((entry, index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={entry.net_pnl >= 0 ? "#10b981" : "#f43f5e"}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}

            {/* 3. Monthly P&L Bars */}
            {activeTab === "monthly" && (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={monthlyData}
                  margin={{ top: 10, right: 10, left: -15, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.4} />
                  <XAxis
                    dataKey="month"
                    stroke="#64748b"
                    fontSize={10}
                    tickLine={false}
                  />
                  <YAxis
                    stroke="#64748b"
                    fontSize={10}
                    tickFormatter={(val) => `$${val}`}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#0f172a",
                      borderColor: "#334155",
                      borderRadius: "6px",
                      fontSize: "11px",
                      color: "#f8fafc",
                    }}
                    formatter={(value: any) => [formatCurrency(Number(value)), "Monthly Net P&L"]}
                    labelFormatter={(label) => `Month: ${label}`}
                  />
                  <ReferenceLine y={0} stroke="#64748b" />
                  <Bar dataKey="net_pnl" isAnimationActive={false}>
                    {monthlyData.map((entry, index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={entry.net_pnl >= 0 ? "#10b981" : "#f43f5e"}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
