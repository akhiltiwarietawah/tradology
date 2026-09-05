"use client";

import React, { useState } from "react";
import { History, Search, ArrowUpDown, Filter } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatDate } from "@/lib/utils";
import type { CumulativePnlPoint } from "@/lib/api/schemas";

interface TradeHistoryProps {
  trades?: CumulativePnlPoint[];
  isLoading?: boolean;
}

export function TradeHistory({ trades = [], isLoading }: TradeHistoryProps) {
  const [searchTerm, setSearchTerm] = useState("");

  if (isLoading) {
    return (
      <Card className="bg-card/60 border-border/80">
        <CardHeader className="pb-3">
          <Skeleton className="h-5 w-48" />
        </CardHeader>
        <CardContent className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </CardContent>
      </Card>
    );
  }

  const filteredTrades = trades.filter((t) =>
    t.trade_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
    t.trade_date.includes(searchTerm)
  );

  return (
    <Card className="bg-card/60 border-border/80 shadow-sm">
      <CardHeader className="py-3 px-4 border-b border-border/60 bg-secondary/10">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <History className="h-4 w-4 text-purple-400" />
            <CardTitle className="text-xs font-semibold text-foreground uppercase tracking-wider">
              Executed Trade History &amp; Settlement
            </CardTitle>
          </div>

          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <input
                type="text"
                placeholder="Search trade ID / date..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="h-7 w-48 bg-background/80 border border-border/60 rounded text-[11px] pl-8 pr-2 font-mono text-foreground focus:outline-none focus:border-border"
              />
            </div>
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-0">
        {filteredTrades.length === 0 ? (
          <div className="py-12 text-center text-xs text-muted-foreground">
            <p className="font-semibold text-foreground">No Completed Trades Recorded</p>
            <p className="text-[11px] mt-1">
              {searchTerm ? "No trades match your search query." : "Settled trades will appear here with execution timestamps and realized net P&L."}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-xs">
              <thead className="bg-secondary/30 text-muted-foreground border-b border-border/60 text-[10px] uppercase tracking-wider">
                <tr>
                  <th className="py-2.5 px-4 font-semibold">Trade ID</th>
                  <th className="py-2.5 px-4 font-semibold">Date</th>
                  <th className="py-2.5 px-4 font-semibold">Strategy</th>
                  <th className="py-2.5 px-4 font-semibold text-right">Realized P&amp;L</th>
                  <th className="py-2.5 px-4 font-semibold text-right">Net P&amp;L</th>
                  <th className="py-2.5 px-4 font-semibold text-right">Cumulative</th>
                  <th className="py-2.5 px-4 font-semibold text-center">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {filteredTrades.map((trade, idx) => {
                  const isPositive = trade.net_pnl >= 0;
                  return (
                    <tr
                      key={trade.trade_id || idx}
                      className="hover:bg-secondary/20 transition-colors"
                    >
                      <td className="py-2.5 px-4 font-medium text-foreground">
                        {trade.trade_id}
                      </td>
                      <td className="py-2.5 px-4 text-muted-foreground">
                        {formatDate(trade.trade_date)}
                      </td>
                      <td className="py-2.5 px-4 text-muted-foreground">
                        <Badge variant="outline" className="text-[9px] px-1.5 py-0 font-mono">
                          0DTE STRANGLE
                        </Badge>
                      </td>
                      <td className="py-2.5 px-4 text-right text-muted-foreground">
                        {formatCurrency(trade.realized_pnl)}
                      </td>
                      <td
                        className={`py-2.5 px-4 text-right font-bold ${
                          isPositive ? "text-emerald-400" : "text-rose-400"
                        }`}
                      >
                        {formatCurrency(trade.net_pnl)}
                      </td>
                      <td className="py-2.5 px-4 text-right font-medium text-foreground">
                        {formatCurrency(trade.cumulative_pnl)}
                      </td>
                      <td className="py-2.5 px-4 text-center">
                        <Badge variant="success" className="text-[9px] px-1.5 py-0">
                          COMPLETED
                        </Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
