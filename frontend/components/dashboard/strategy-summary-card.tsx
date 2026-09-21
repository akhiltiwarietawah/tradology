"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatCurrency } from "@/lib/utils";
import { PnlSparkline } from "@/components/dashboard/pnl-sparkline";
import type { EngineStrategyDef } from "@/lib/engine-strategies";
import type { PerformanceMetricsResponse, RenkoSnapshot } from "@/lib/api/schemas";
import { renkoUnrealizedPnl } from "@/components/dashboard/renko-panel";

interface StrategySummaryCardProps {
  strategy: EngineStrategyDef;
  metrics?: PerformanceMetricsResponse | null;
  snapshot?: RenkoSnapshot | null;
  strangleOpen?: boolean;
  isLoading?: boolean;
}

export function StrategySummaryCard({
  strategy,
  metrics,
  snapshot,
  strangleOpen,
  isLoading,
}: StrategySummaryCardProps) {
  const curve = (metrics?.cumulative_pnl_curve || []).map((p) => p.cumulative_pnl);
  const net = metrics?.net_pnl ?? 0;
  const upl = strategy.kind === "renko" ? renkoUnrealizedPnl(snapshot) : null;
  const open =
    strategy.kind === "renko" ? (snapshot?.position ?? 0) !== 0 : Boolean(strangleOpen);
  const enabled = strategy.kind === "renko" ? Boolean(snapshot?.enabled) : true;

  return (
    <Link href={`/engine/${strategy.slug}`} className="block group">
      <Card className="bg-card/70 border-border/80 h-full transition-colors group-hover:border-emerald-500/30">
        <CardContent className="p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <div>
              <p className="text-sm font-semibold">{strategy.label}</p>
              <p className="text-[10px] font-mono text-muted-foreground">{strategy.code}</p>
            </div>
            <Badge variant={open ? "success" : enabled ? "outline" : "secondary"} className="text-[10px]">
              {open ? "OPEN" : enabled ? "FLAT" : "OFF"}
            </Badge>
          </div>

          <div className="grid grid-cols-2 gap-3 text-xs font-mono">
            <div>
              <span className="text-[10px] text-muted-foreground block">Net P&amp;L</span>
              <span className={net >= 0 ? "text-emerald-400 font-semibold" : "text-rose-400 font-semibold"}>
                {isLoading ? "--" : formatCurrency(net)}
              </span>
            </div>
            <div>
              <span className="text-[10px] text-muted-foreground block">UPL</span>
              <span className={(upl ?? 0) >= 0 ? "text-emerald-400 font-semibold" : "text-rose-400 font-semibold"}>
                {strategy.kind === "renko" ? formatCurrency(upl) : strangleOpen ? "Open" : "--"}
              </span>
            </div>
          </div>

          <PnlSparkline values={curve} className="h-14 w-full" />

          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
            <span>{metrics?.total_trades ?? 0} trades</span>
            <span className="inline-flex items-center gap-1 text-emerald-400 group-hover:underline">
              Open page <ArrowRight className="h-3 w-3" />
            </span>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
