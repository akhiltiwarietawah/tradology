"use client";

import { Activity } from "lucide-react";
import { PageHeader, EmptyState } from "@/components/ui/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePlatformTrades } from "@/hooks/usePlatform";
import { cn, formatCurrency, formatDate } from "@/lib/utils";

export default function TradesPage() {
  const { data, isLoading, isError } = usePlatformTrades({ limit: 100 });
  const trades = data?.trades ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Trades"
        description="Your attributed platform trades only. Legacy global engine trades are excluded."
        icon={Activity}
      />

      {isLoading && <Skeleton className="h-64 w-full rounded-xl" />}
      {isError && (
        <EmptyState title="Unable to load trades" description="Ensure platform database is connected." />
      )}

      {!isLoading && !isError && trades.length === 0 && (
        <EmptyState
          title="Not available yet"
          description="Attributed trades appear here after platform strategy execution with linked accounts."
        />
      )}

      {!isLoading && !isError && trades.length > 0 && (
        <Card className="bg-card/60 border-border/80">
          <CardHeader className="py-3 px-4 border-b border-border/60">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider">
              Platform Trades ({trades.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-left font-mono text-xs">
                <thead className="bg-secondary/30 text-muted-foreground border-b border-border/60 text-[10px] uppercase">
                  <tr>
                    <th className="py-2.5 px-4">Trade ID</th>
                    <th className="py-2.5 px-4">Strategy</th>
                    <th className="py-2.5 px-4">Opened</th>
                    <th className="py-2.5 px-4 text-right">Entry</th>
                    <th className="py-2.5 px-4 text-right">Exit</th>
                    <th className="py-2.5 px-4 text-right">Realized P&L</th>
                    <th className="py-2.5 px-4 text-right">Fees</th>
                    <th className="py-2.5 px-4 text-center">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/40">
                  {trades.map((trade) => {
                    const positive = (trade.realized_pnl ?? 0) >= 0;
                    return (
                      <tr key={trade.trade_id} className="hover:bg-secondary/20">
                        <td className="py-2.5 px-4">{trade.trade_id}</td>
                        <td className="py-2.5 px-4">
                          <Badge variant="outline" className="text-[9px]">
                            {trade.strategy}
                          </Badge>
                        </td>
                        <td className="py-2.5 px-4 text-muted-foreground">
                          {trade.opened_at ? formatDate(trade.opened_at) : "—"}
                        </td>
                        <td className="py-2.5 px-4 text-right">{formatCurrency(trade.entry ?? 0)}</td>
                        <td className="py-2.5 px-4 text-right">{formatCurrency(trade.exit ?? 0)}</td>
                        <td
                          className={cn(
                            "py-2.5 px-4 text-right font-semibold",
                            positive ? "text-emerald-400" : "text-rose-400",
                          )}
                        >
                          {formatCurrency(trade.realized_pnl ?? 0)}
                        </td>
                        <td className="py-2.5 px-4 text-right">{formatCurrency(trade.fees ?? 0)}</td>
                        <td className="py-2.5 px-4 text-center">
                          <Badge variant="secondary" className="text-[9px]">
                            {trade.status}
                          </Badge>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
