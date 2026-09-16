"use client";

import Link from "next/link";
import { Waypoints } from "lucide-react";
import { PageHeader, EmptyState } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { buttonVariants } from "@/components/ui/button";
import { StrategyCard } from "@/components/platform/strategy-card";
import { cn } from "@/lib/utils";
import { usePlatformStrategies, usePlatformSubscriptions } from "@/hooks/usePlatform";

export default function StrategiesPage() {
  const { data, isLoading, isError } = usePlatformStrategies();
  const { data: subsData } = usePlatformSubscriptions();
  const strategies = data?.strategies ?? [];
  const subscribedCodes = new Set(
    (subsData?.subscriptions ?? []).map((s: any) => s.strategy?.code).filter(Boolean),
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Strategies"
        description="Discover algorithmic strategies. Subscribe once, then run independently on each connected exchange account."
        icon={Waypoints}
        action={
          subscribedCodes.size > 0 ? (
            <Link href="/my-strategies" className={cn(buttonVariants({ size: "sm", variant: "outline" }))}>
              My Strategies
            </Link>
          ) : undefined
        }
      />

      {isLoading && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-56 w-full rounded-xl" />
          ))}
        </div>
      )}

      {isError && (
        <EmptyState
          title="Unable to load strategies"
          description="Ensure PostgreSQL is running and platform migrations have been applied."
        />
      )}

      {!isLoading && !isError && strategies.length === 0 && (
        <EmptyState title="No strategies available" description="Run database migrations to seed the strategy catalog." />
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {strategies.map((strategy) => (
          <StrategyCard key={strategy.id} strategy={strategy} subscribed={subscribedCodes.has(strategy.code)} />
        ))}
      </div>
    </div>
  );
}
