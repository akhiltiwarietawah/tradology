"use client";

import Link from "next/link";
import { Wallet } from "lucide-react";
import { PageHeader, EmptyState } from "@/components/ui/page-header";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatCurrency, formatRelativeTime, healthBadgeVariant } from "@/lib/utils";
import { usePlatformAccounts } from "@/hooks/usePlatform";

export default function AccountsPage() {
  const { data, isLoading } = usePlatformAccounts();
  const accounts = data?.accounts ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Exchange Accounts"
        description="Connected accounts with encrypted credentials stored server-side only."
        icon={Wallet}
        action={
          <Link href="/connect" className={cn(buttonVariants({ size: "sm" }))}>
            Connect Exchange
          </Link>
        }
      />

      {isLoading && <Skeleton className="h-32 w-full rounded-xl" />}

      {!isLoading && accounts.length === 0 && (
        <EmptyState
          title="No exchange accounts connected"
          description="Connect Binance, Bybit, OKX, or Delta to sync balances, positions, and equity history."
          action={
            <Link href="/connect" className={cn(buttonVariants({ size: "sm" }))}>
              Connect Exchanges
            </Link>
          }
        />
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {accounts.map((account) => {
          const health = account.health_status || account.status || account.connection_status;
          return (
            <Link key={account.id} href={`/accounts/${account.id}`}>
              <Card className="bg-card/60 border-border/70 hover:border-emerald-500/20 transition-colors h-full">
                <CardContent className="p-5 space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="font-semibold">{account.label}</h3>
                    <Badge variant="outline" className="text-[10px] uppercase">
                      {account.exchange}
                    </Badge>
                  </div>
                  <p className="text-xl font-mono font-semibold">
                    {formatCurrency(account.equity ?? account.balance ?? 0)}
                  </p>
                  <div className="flex items-center justify-between text-xs font-mono">
                    <span className="text-muted-foreground">Status</span>
                    <Badge variant={healthBadgeVariant(health)}>{health}</Badge>
                  </div>
                  <p className="text-[11px] text-muted-foreground">
                    {account.is_testnet ? "Testnet" : "Live"} • Last sync{" "}
                    {formatRelativeTime(account.last_synced_at || account.last_sync_at)}
                  </p>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
