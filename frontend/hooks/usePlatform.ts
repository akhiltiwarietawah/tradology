"use client";

import { useEffect } from "react";
import { useSession } from "next-auth/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { platformApi, type EquityRange } from "@/lib/api/platform-client";

export function usePlatformUserSync() {
  const { data: session, status } = useSession();

  useEffect(() => {
    if (status !== "authenticated" || !session?.user?.email) return;

    platformApi
      .syncUser({
        email: session.user.email,
        name: session.user.name,
        avatar_url: session.user.image,
      })
      .catch(() => {
        // Backend may be offline during local dev
      });
  }, [status, session]);
}

export function usePlatformEvents() {
  const queryClient = useQueryClient();

  useEffect(() => {
    const url = platformApi.getEventsStreamUrl();
    const es = new EventSource(url);

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const type = data?.type as string | undefined;
        const accountId = data?.payload?.account_id as string | undefined;

        if (type?.startsWith("account.")) {
          queryClient.invalidateQueries({ queryKey: ["platformAccounts"] });
          queryClient.invalidateQueries({ queryKey: ["platformDashboardSummary"] });
          if (accountId) {
            queryClient.invalidateQueries({ queryKey: ["platformAccountDetail", accountId] });
            queryClient.invalidateQueries({ queryKey: ["platformEquityCurve", accountId] });
          }
        }

        if (type?.startsWith("strategy.")) {
          queryClient.invalidateQueries({ queryKey: ["platformSubscriptions"] });
          queryClient.invalidateQueries({ queryKey: ["platformStrategyRuntimes"] });
          queryClient.invalidateQueries({ queryKey: ["platformDashboardSummary"] });
          queryClient.invalidateQueries({ queryKey: ["platformPortfolioPerformance"] });
        }
      } catch {
        // Ignore malformed SSE payloads
      }
    };

    return () => es.close();
  }, [queryClient]);
}

export function usePlatformStrategies() {
  return useQuery({
    queryKey: ["platformStrategies"],
    queryFn: () => platformApi.listStrategies(),
    staleTime: 30000,
  });
}

export function usePlatformSubscriptions() {
  return useQuery({
    queryKey: ["platformSubscriptions"],
    queryFn: () => platformApi.listSubscriptions(),
    staleTime: 15000,
  });
}

export function usePlatformAccounts() {
  return useQuery({
    queryKey: ["platformAccounts"],
    queryFn: () => platformApi.listAccounts(),
    staleTime: 15000,
  });
}

export function usePlatformAccountDetail(accountId: string) {
  return useQuery({
    queryKey: ["platformAccountDetail", accountId],
    queryFn: () => platformApi.getAccountDetail(accountId),
    enabled: !!accountId,
    staleTime: 10000,
  });
}

export function usePlatformEquityCurve(accountId: string, range: EquityRange) {
  return useQuery({
    queryKey: ["platformEquityCurve", accountId, range],
    queryFn: () => platformApi.getEquityCurve(accountId, range),
    enabled: !!accountId,
    staleTime: 30000,
  });
}

export function usePlatformDashboardSummary() {
  return useQuery({
    queryKey: ["platformDashboardSummary"],
    queryFn: () => platformApi.getDashboardSummary(),
    staleTime: 10000,
    refetchInterval: 60000,
  });
}

export function useSubscribeStrategy() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (code: string) => platformApi.subscribe(code),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platformSubscriptions"] });
      queryClient.invalidateQueries({ queryKey: ["platformDashboardSummary"] });
    },
  });
}

export function useLinkStrategyAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      subscriptionId,
      exchangeAccountId,
      executionMode = "PAPER",
      allocationPct = 100,
      riskOverrides = {},
      confirmLive = false,
      status = "paused",
    }: {
      subscriptionId: string;
      exchangeAccountId: string;
      executionMode?: "PAPER" | "LIVE" | "LIVE_DRY_RUN";
      allocationPct?: number;
      riskOverrides?: Record<string, unknown>;
      confirmLive?: boolean;
      status?: string;
    }) =>
      platformApi.linkStrategyAccount(subscriptionId, {
        exchange_account_id: exchangeAccountId,
        execution_mode: executionMode,
        allocation_pct: allocationPct,
        risk_overrides: riskOverrides,
        confirm_live: confirmLive,
        status,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platformSubscriptions"] });
      queryClient.invalidateQueries({ queryKey: ["platformDashboardSummary"] });
      queryClient.invalidateQueries({ queryKey: ["platformAccountStrategies"] });
      queryClient.invalidateQueries({ queryKey: ["platformPortfolioPerformance"] });
    },
  });
}

export function usePlatformPortfolioPerformance(params?: {
  range?: EquityRange;
  strategy?: string;
  account_id?: string;
}) {
  return useQuery({
    queryKey: ["platformPortfolioPerformance", params?.range, params?.strategy, params?.account_id],
    queryFn: () => platformApi.getPortfolioPerformance(params),
    staleTime: 30000,
  });
}

export function usePlatformTrades(params?: {
  strategy?: string;
  strategy_account_id?: string;
  account_id?: string;
  status?: string;
  limit?: number;
}) {
  return useQuery({
    queryKey: ["platformTrades", params?.strategy, params?.strategy_account_id, params?.account_id, params?.status],
    queryFn: () => platformApi.getPlatformTrades(params),
    staleTime: 15000,
  });
}

export function useAccountStrategies(accountId: string) {
  return useQuery({
    queryKey: ["platformAccountStrategies", accountId],
    queryFn: () => platformApi.getAccountStrategies(accountId),
    enabled: !!accountId,
    staleTime: 15000,
  });
}

export function useStrategyAccountDetail(strategyAccountId: string) {
  return useQuery({
    queryKey: ["platformStrategyAccount", strategyAccountId],
    queryFn: () => platformApi.getStrategyAccount(strategyAccountId),
    enabled: !!strategyAccountId,
    staleTime: 15000,
  });
}

export function useTestExchangeConnection() {
  return useMutation({
    mutationFn: platformApi.testConnection.bind(platformApi),
  });
}

export function useConnectExchangeAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: platformApi.connectAccount.bind(platformApi),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platformAccounts"] });
      queryClient.invalidateQueries({ queryKey: ["platformDashboardSummary"] });
    },
  });
}

export function useSyncExchangeAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) => platformApi.syncAccount(accountId),
    onSuccess: (_data, accountId) => {
      queryClient.invalidateQueries({ queryKey: ["platformAccounts"] });
      queryClient.invalidateQueries({ queryKey: ["platformDashboardSummary"] });
      queryClient.invalidateQueries({ queryKey: ["platformAccountDetail", accountId] });
      queryClient.invalidateQueries({ queryKey: ["platformEquityCurve", accountId] });
    },
  });
}

export function useSupportedExchanges() {
  return useQuery({
    queryKey: ["supportedExchanges"],
    queryFn: () => platformApi.getSupportedExchanges(),
    staleTime: 60000,
  });
}

export function usePlatformStrategyRuntimes() {
  return useQuery({
    queryKey: ["platformStrategyRuntimes"],
    queryFn: () => platformApi.listStrategyRuntimes(),
    staleTime: 10000,
    refetchInterval: 15000,
  });
}

export function useStrategyRuntimeControl() {
  const queryClient = useQueryClient();
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["platformStrategyRuntimes"] });
    queryClient.invalidateQueries({ queryKey: ["platformSubscriptions"] });
    queryClient.invalidateQueries({ queryKey: ["platformAccountDetail"] });
  };

  return {
    start: useMutation({ mutationFn: platformApi.startStrategyRuntime.bind(platformApi), onSuccess: invalidate }),
    stop: useMutation({ mutationFn: platformApi.stopStrategyRuntime.bind(platformApi), onSuccess: invalidate }),
    pause: useMutation({ mutationFn: platformApi.pauseStrategyRuntime.bind(platformApi), onSuccess: invalidate }),
    resume: useMutation({ mutationFn: platformApi.resumeStrategyRuntime.bind(platformApi), onSuccess: invalidate }),
    enableTrading: useMutation({
      mutationFn: ({ id, confirmLive }: { id: string; confirmLive?: boolean }) =>
        platformApi.enableStrategyTrading(id, confirmLive),
      onSuccess: invalidate,
    }),
    disableTrading: useMutation({
      mutationFn: platformApi.disableStrategyTrading.bind(platformApi),
      onSuccess: invalidate,
    }),
    setMode: useMutation({
      mutationFn: ({ id, mode, confirmLive }: { id: string; mode: "PAPER" | "LIVE" | "LIVE_DRY_RUN"; confirmLive?: boolean }) =>
        platformApi.setStrategyExecutionMode(id, mode, confirmLive),
      onSuccess: invalidate,
    }),
    recover: useMutation({
      mutationFn: platformApi.recoverStrategyRuntime.bind(platformApi),
      onSuccess: invalidate,
    }),
  };
}
