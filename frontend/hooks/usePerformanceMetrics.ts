"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient, ApiClientError, type PerformanceQueryParams } from "@/lib/api/client";
import type { PerformanceMetricsResponse } from "@/lib/api/schemas";

export function usePerformanceMetrics(params?: PerformanceQueryParams) {
  const queryKey = [
    "performanceMetrics",
    params?.start_date,
    params?.end_date,
    params?.strategy_name,
    params?.exchange,
  ];

  const query = useQuery<PerformanceMetricsResponse, ApiClientError>({
    queryKey,
    queryFn: () => apiClient.getPerformance(params),
    staleTime: 30000, // 30 seconds cache for historical metrics
    refetchInterval: 60000, // Background refresh every 60s (avoids unnecessary spam)
    retry: 1,
  });

  const metrics = query.data;
  const hasTrades = (metrics?.total_trades ?? 0) > 0;
  const isNetProfitable = (metrics?.net_pnl ?? 0) >= 0;

  return {
    ...query,
    metrics,
    hasTrades,
    isNetProfitable,
    cumulativeCurve: metrics?.cumulative_pnl_curve ?? [],
    dailyPnl: metrics?.daily_pnl ?? [],
    monthlyPnl: metrics?.monthly_pnl ?? [],
  };
}
