"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "@/lib/api/client";
import type { ReadinessResponse } from "@/lib/api/schemas";

export function useReadiness(pollingIntervalMs: number = 5000) {
  const query = useQuery<ReadinessResponse, ApiClientError>({
    queryKey: ["readiness"],
    queryFn: () => apiClient.getReadiness(),
    refetchInterval: pollingIntervalMs,
    staleTime: 3000,
    retry: 1,
  });

  return {
    ...query,
    readiness: query.data,
    isReady: query.data?.ready ?? false,
    engine: query.data?.engine ?? "STOPPED",
    exchange: query.data?.exchange ?? "UNAVAILABLE",
    reconciliation: query.data?.reconciliation ?? "UNSYNCHRONIZED",
  };
}
