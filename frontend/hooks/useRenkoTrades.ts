"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "@/lib/api/client";
import type { RenkoTradesResponse } from "@/lib/api/schemas";

export function useRenkoTrades(limit: number = 50, strategyName?: string, enabled: boolean = true) {
  const query = useQuery<RenkoTradesResponse, ApiClientError>({
    queryKey: ["renkoTrades", limit, strategyName],
    queryFn: () => apiClient.getRenkoTrades(limit, strategyName),
    staleTime: 10000,
    refetchInterval: 30000,
    retry: 1,
    enabled,
  });

  return {
    ...query,
    trades: query.data?.trades ?? [],
    openTrade: query.data?.open_trade ?? null,
    dbConnected: query.data?.connected ?? false,
  };
}
