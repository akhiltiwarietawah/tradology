"use client";

import { useState } from "react";
import { CandlestickChart, Search } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatDateTime } from "@/lib/utils";
import type { RenkoTradeRecord } from "@/lib/api/schemas";

interface RenkoTradeHistoryProps {
  trades?: RenkoTradeRecord[];
  openTrade?: RenkoTradeRecord | null;
  isLoading?: boolean;
  dbConnected?: boolean;
}

export function RenkoTradeHistory({
  trades = [],
  openTrade,
  isLoading,
  dbConnected = true,
}: RenkoTradeHistoryProps) {
  const [searchTerm, setSearchTerm] = useState("");

  if (isLoading) {
    return (
      <Card className="bg-card/60 border-border/80">
        <CardHeader className="pb-3">
          <Skeleton className="h-5 w-48" />
        </CardHeader>
        <CardContent className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </CardContent>
      </Card>
    );
  }

  const filtered = trades.filter(
    (t) =>
      t.trade_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (t.trade_date || "").includes(searchTerm)
  );

  return (
    <Card className="bg-card/60 border-border/80 shadow-sm">
      <CardHeader className="py-3 px-4 border-b border-border/60 bg-secondary/10">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <CandlestickChart className="h-4 w-4 text-violet-400" />
            <CardTitle className="text-xs font-semibold uppercase tracking-wider">
              Renko Trade History (PostgreSQL)
            </CardTitle>
            {!dbConnected && (
              <Badge variant="warning" className="text-[10px]">
                DB OFFLINE
              </Badge>
            )}
          </div>

          <div className="relative">
            <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search trade ID..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="h-7 w-48 bg-background/80 border border-border/60 rounded text-[11px] pl-8 pr-2 font-mono focus:outline-none focus:border-border"
            />
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-0">
        {openTrade && (
          <div className="px-4 py-3 border-b border-border/40 bg-violet-500/5 text-xs font-mono">
            <span className="text-muted-foreground mr-2">Open:</span>
            <span className="text-foreground font-semibold">{openTrade.trade_id}</span>
            <span className="mx-2 text-border">•</span>
            <Badge variant="success" className="text-[10px] mr-2">
              {openTrade.status}
            </Badge>
            {openTrade.legs?.[0] && (
              <>
                <span className="text-muted-foreground">
                  {openTrade.legs[0].leg_type} @ {formatCurrency(openTrade.legs[0].entry_price)}
                </span>
              </>
            )}
          </div>
        )}

        {filtered.length === 0 ? (
          <div className="py-12 text-center text-xs text-muted-foreground">
            <p className="font-semibold text-foreground">No Renko trades in database</p>
            <p className="text-[11px] mt-1">
              {dbConnected
                ? "Completed round-trips will appear here after exit fills."
                : "PostgreSQL is unavailable — using JSONL fallback on the engine."}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-xs">
              <thead className="bg-secondary/30 text-muted-foreground border-b border-border/60 text-[10px] uppercase tracking-wider">
                <tr>
                  <th className="py-2.5 px-4 font-semibold">Trade ID</th>
                  <th className="py-2.5 px-4 font-semibold">Status</th>
                  <th className="py-2.5 px-4 font-semibold">Side</th>
                  <th className="py-2.5 px-4 font-semibold">Entry</th>
                  <th className="py-2.5 px-4 font-semibold">Exit</th>
                  <th className="py-2.5 px-4 font-semibold">Net P&amp;L</th>
                  <th className="py-2.5 px-4 font-semibold">Closed</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {filtered.map((trade) => {
                  const leg = trade.legs?.[0];
                  const netPnl = trade.net_pnl ?? 0;
                  return (
                    <tr key={trade.trade_id} className="hover:bg-secondary/20 transition-colors">
                      <td className="py-2.5 px-4 text-foreground">{trade.trade_id}</td>
                      <td className="py-2.5 px-4">
                        <Badge
                          variant={trade.status === "COMPLETED" ? "secondary" : "success"}
                          className="text-[10px]"
                        >
                          {trade.status}
                        </Badge>
                      </td>
                      <td className="py-2.5 px-4">{leg?.leg_type || "--"}</td>
                      <td className="py-2.5 px-4">{formatCurrency(leg?.entry_price)}</td>
                      <td className="py-2.5 px-4">{formatCurrency(leg?.exit_price)}</td>
                      <td
                        className={`py-2.5 px-4 font-semibold ${
                          netPnl >= 0 ? "text-emerald-400" : "text-rose-400"
                        }`}
                      >
                        {formatCurrency(netPnl)}
                      </td>
                      <td className="py-2.5 px-4 text-muted-foreground">
                        {trade.exit_time ? formatDateTime(trade.exit_time) : "--"}
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
