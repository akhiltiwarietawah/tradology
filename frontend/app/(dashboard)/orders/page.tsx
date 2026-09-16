"use client";

import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { ListOrdered } from "lucide-react";
import { PageHeader, EmptyState } from "@/components/ui/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePlatformAccounts } from "@/hooks/usePlatform";
import { platformApi } from "@/lib/api/platform-client";
import { formatNumber } from "@/lib/utils";

export default function OrdersPage() {
  const { data: accountsData, isLoading: accountsLoading } = usePlatformAccounts();
  const accountList = useMemo(() => accountsData?.accounts ?? [], [accountsData?.accounts]);

  const detailQueries = useQueries({
    queries: accountList.map((account) => ({
      queryKey: ["platformAccountDetail", account.id],
      queryFn: () => platformApi.getAccountDetail(account.id),
      staleTime: 15000,
    })),
  });

  const orders = useMemo(() => {
    return detailQueries.flatMap((query, idx) => {
      const account = accountList[idx];
      return (query.data?.orders ?? []).map((order) => ({
        ...order,
        accountLabel: account?.label,
        exchange: account?.exchange,
      }));
    });
  }, [detailQueries, accountList]);

  const isLoading = accountsLoading || detailQueries.some((q) => q.isLoading);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Orders"
        description="Open orders synced from connected exchange accounts."
        icon={ListOrdered}
      />

      {isLoading && <Skeleton className="h-48 w-full rounded-xl" />}

      {!isLoading && !accountList.length && (
        <EmptyState
          title="No connected accounts"
          description="Connect an exchange account to sync open orders."
        />
      )}

      {!isLoading && accountList.length > 0 && orders.length === 0 && (
        <EmptyState title="No open orders" description="All connected accounts have no open orders right now." />
      )}

      {!!orders.length && (
        <Card className="bg-card/60 border-border/70">
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-muted-foreground border-b border-border/50">
                    {["Account", "Exchange", "Symbol", "Side", "Type", "Qty", "Price", "Status"].map((h) => (
                      <th key={h} className="text-left font-medium px-4 py-2.5">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {orders.map((order) => (
                    <tr key={`${order.exchange_order_id}-${order.symbol}`} className="border-b border-border/30">
                      <td className="px-4 py-2.5">{order.accountLabel}</td>
                      <td className="px-4 py-2.5 uppercase">{order.exchange}</td>
                      <td className="px-4 py-2.5 font-mono">{order.symbol}</td>
                      <td className="px-4 py-2.5">{order.side}</td>
                      <td className="px-4 py-2.5">{order.order_type || "--"}</td>
                      <td className="px-4 py-2.5 font-mono">{formatNumber(order.quantity, 4)}</td>
                      <td className="px-4 py-2.5 font-mono">{formatNumber(order.price)}</td>
                      <td className="px-4 py-2.5">{order.status || "--"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
