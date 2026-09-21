"use client";

import { usePerformanceMetrics } from "@/hooks/usePerformanceMetrics";
import { StrategySummaryCard } from "@/components/dashboard/strategy-summary-card";
import type { EngineStrategyDef } from "@/lib/engine-strategies";
import type { RenkoSnapshot } from "@/lib/api/schemas";

interface StrategySummaryCardLoaderProps {
  strategy: EngineStrategyDef;
  snapshot?: RenkoSnapshot | null;
  strangleOpen?: boolean;
}

export function StrategySummaryCardLoader({
  strategy,
  snapshot,
  strangleOpen,
}: StrategySummaryCardLoaderProps) {
  const { metrics, isLoading } = usePerformanceMetrics({ strategy_name: strategy.code });

  return (
    <StrategySummaryCard
      strategy={strategy}
      metrics={metrics}
      isLoading={isLoading}
      snapshot={snapshot}
      strangleOpen={strangleOpen}
    />
  );
}
