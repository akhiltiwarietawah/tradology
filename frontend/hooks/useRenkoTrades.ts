"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "@/lib/api/client";
import type { RenkoTradesResponse } from "@/lib/api/schemas";

export function useRenkoTrades(limit: number = 50) {
  const query = useQuery<RenkoTradesResponse, ApiClientError>({
    queryKey: ["renkoTrades", limit],
    queryFn: () => apiClient.getRenkoTrades(limit),
    staleTime: 10000,
    refetchInterval: 30000,
    retry: 1,
  });

  return {
    ...query,
    trades: query.data?.trades ?? [],
    openTrade: query.data?.open_trade ?? null,
    dbConnected: query.data?.connected ?? false,
  };
}
