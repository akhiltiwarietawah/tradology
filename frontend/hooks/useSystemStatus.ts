"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "@/lib/api/client";
import type { SystemStatusResponse } from "@/lib/api/schemas";

export interface UseSystemStatusOptions {
  pollingIntervalMs?: number;
  enabled?: boolean;
}

export function useSystemStatus(options?: UseSystemStatusOptions) {
  const pollingInterval = options?.pollingIntervalMs ?? 2500; // 2.5s live polling
  const enabled = options?.enabled ?? true;

  const query = useQuery<SystemStatusResponse, ApiClientError>({
    queryKey: ["systemStatus"],
    queryFn: () => apiClient.getStatus(),
    refetchInterval: enabled ? pollingInterval : false,
    staleTime: 1500,
    retry: 2,
    enabled,
  });

  const isNetworkError =
    query.isError && (query.error?.isNetworkError || query.error?.isTimeout);

  const engineStatus = query.data?.engine?.status || "STOPPED";
  const isSafeHalt = engineStatus === "SAFE_HALT";
  const isRunning = engineStatus === "RUNNING";
  const isExchangeConnected = query.data?.exchange?.rest_connected ?? false;
  const isWsStale = query.data?.exchange?.ws_stale ?? false;
  const isSynchronized = query.data?.reconciliation?.is_synchronized ?? false;
  const isDbConnected = query.data?.database?.connected ?? false;
  const hasActiveTrade = !!(query.data?.current_trade && query.data?.current_trade?.trade_id);

  return {
    ...query,
    statusData: query.data,
    isNetworkError,
    isSafeHalt,
    isRunning,
    isExchangeConnected,
    isWsStale,
    isSynchronized,
    isDbConnected,
    hasActiveTrade,
    activeTrade: query.data?.current_trade ?? null,
    recentAlerts: query.data?.alerts?.recent_alerts ?? [],
  };
}
