"use client";

import Link from "next/link";
import { ExternalLink, Layers } from "lucide-react";
import { PageHeader, EmptyState } from "@/components/ui/page-header";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatCurrency, formatRelativeTime, runtimeStatusVariant } from "@/lib/utils";
import { usePlatformAccounts, usePlatformSubscriptions } from "@/hooks/usePlatform";
import { StrategyRuntimeControls } from "@/components/platform/strategy-runtime-controls";

export default function MyStrategiesPage() {
  const { data, isLoading } = usePlatformSubscriptions();
  const { data: accountsData } = usePlatformAccounts();
  const subscriptions = data?.subscriptions ?? [];
  const accountsById = Object.fromEntries((accountsData?.accounts ?? []).map((a) => [a.id, a]));

  return (
    <div className="space-y-6">
      <PageHeader
        title="My Strategies"
        description="Control center for subscribed strategies. Each linked exchange account runs with isolated runtime state."
        icon={Layers}
        action={
          <Link href="/strategies" className={cn(buttonVariants({ size: "sm", variant: "outline" }))}>
            Browse Strategies
          </Link>
        }
      />

      {isLoading && <Skeleton className="h-40 w-full rounded-xl" />}

      {!isLoading && subscriptions.length === 0 && (
        <EmptyState
          title="No active subscriptions"
          description="Subscribe to a strategy, connect an exchange account, and complete the setup wizard."
          action={
            <Link href="/strategies" className={cn(buttonVariants({ size: "sm" }))}>
              Explore Strategies
            </Link>
          }
        />
      )}

      <div className="space-y-4">
        {subscriptions.map((sub: any) => (
          <Card key={sub.id} className="bg-card/50 border-border/70">
            <CardContent className="p-5 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <Link href={`/strategies/${sub.strategy?.code}`} className="font-semibold hover:text-emerald-300">
                    {sub.strategy?.name || "Strategy"}
                  </Link>
                  <p className="text-xs text-muted-foreground font-mono">{sub.strategy?.code}</p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant={sub.status === "ACTIVE" ? "success" : "secondary"}>{sub.status}</Badge>
                  <Link
                    href={`/strategies/${sub.strategy?.code}/subscribe`}
                    className={cn(buttonVariants({ size: "sm", variant: "outline" }), "h-8 text-xs")}
                  >
                    Link Account
                  </Link>
                </div>
              </div>

              <div className="space-y-3">
                <p className="text-[11px] uppercase tracking-wider text-muted-foreground">Linked Accounts & Runtimes</p>
                {(sub.linked_accounts || []).length === 0 ? (
                  <div className="rounded-lg border border-dashed border-border/60 p-4 text-xs text-muted-foreground">
                    No accounts linked yet.{" "}
                    <Link href={`/strategies/${sub.strategy?.code}/subscribe`} className="text-emerald-400 underline">
                      Complete subscription setup
                    </Link>
                  </div>
                ) : (
                  (sub.linked_accounts || []).map((link: any) => {
                    const account = accountsById[link.exchange_account_id];
                    return (
                      <div key={link.id} className="rounded-lg border border-border/60 bg-background/20 p-4 space-y-3">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <div className="flex items-center gap-2">
                              <p className="text-sm font-medium">{account?.label || link.exchange_account_id.slice(0, 8)}</p>
                              <Badge variant={runtimeStatusVariant(link.runtime_status || "STOPPED")} className="text-[10px]">
                                {link.runtime_status || "STOPPED"}
                              </Badge>
                            </div>
                            <p className="text-[10px] uppercase text-muted-foreground">{account?.exchange}</p>
                            <p className="text-[10px] text-muted-foreground mt-1">
                              Mode: {link.execution_mode || "PAPER"} • Trading: {link.trading_enabled ? "ON" : "OFF"}
                            </p>
                            {link.last_heartbeat_at && (
                              <p className="text-[10px] text-muted-foreground">
                                Heartbeat {formatRelativeTime(link.last_heartbeat_at)}
                              </p>
                            )}
                          </div>
                          <div className="text-right space-y-1">
                            {account && (
                              <p className="text-sm font-mono font-semibold">
                                {formatCurrency(account.equity ?? account.balance ?? 0)}
                              </p>
                            )}
                            <div className="flex items-center gap-2 justify-end">
                              <Link
                                href={`/execution/${link.id}`}
                                className="text-[10px] text-muted-foreground hover:text-emerald-300 inline-flex items-center gap-1"
                              >
                                Validation <ExternalLink className="h-3 w-3" />
                              </Link>
                              {account && (
                                <Link
                                  href={`/accounts/${account.id}`}
                                  className="text-[10px] text-muted-foreground hover:text-emerald-300"
                                >
                                  Account
                                </Link>
                              )}
                            </div>
                          </div>
                        </div>
                        <StrategyRuntimeControls
                          strategyAccountId={link.id}
                          executionMode={link.execution_mode || "PAPER"}
                          tradingEnabled={!!link.trading_enabled}
                          runtimeStatus={link.runtime_status || "STOPPED"}
                          exchangeLabel={account?.label}
                          lastHeartbeat={link.last_heartbeat_at}
                          compact
                        />
                      </div>
                    );
                  })
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
