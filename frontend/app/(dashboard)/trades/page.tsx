"use client";

import { useState } from "react";
import { Activity } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { RenkoTradeHistory } from "@/components/dashboard/renko-trade-history";
import { TradeHistory } from "@/components/dashboard/trade-history";
import { useRenkoTrades } from "@/hooks/useRenkoTrades";
import { usePerformanceMetrics } from "@/hooks/usePerformanceMetrics";
import { ENGINE_STRATEGIES, type EngineStrategySlug } from "@/lib/engine-strategies";
import { cn } from "@/lib/utils";

export default function TradesPage() {
  const [slug, setSlug] = useState<EngineStrategySlug>("eth");
  const strategy = ENGINE_STRATEGIES.find((s) => s.slug === slug)!;
  const renko = useRenkoTrades(100, strategy.code, strategy.kind === "renko");
  const strangle = usePerformanceMetrics({ strategy_name: "short_strangle" });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Trades"
        description="One strategy at a time. Switch tabs to see that book's history only."
        icon={Activity}
      />

      <div className="flex flex-wrap gap-2">
        {ENGINE_STRATEGIES.map((s) => (
          <button
            key={s.slug}
            type="button"
            onClick={() => setSlug(s.slug)}
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-semibold border",
              slug === s.slug
                ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                : "text-muted-foreground border-border/60 hover:bg-secondary/50"
            )}
          >
            {s.label}
          </button>
        ))}
      </div>

      {strategy.kind === "renko" ? (
        <RenkoTradeHistory
          trades={renko.trades}
          openTrade={renko.openTrade}
          isLoading={renko.isLoading}
          dbConnected={renko.dbConnected}
          title={strategy.label}
        />
      ) : (
        <TradeHistory
          trades={strangle.metrics?.cumulative_pnl_curve || []}
          isLoading={strangle.isLoading}
        />
      )}
    </div>
  );
}
