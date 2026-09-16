"use client";

import { useMemo } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Waypoints } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { PageHeader, EmptyState } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { buttonVariants } from "@/components/ui/button";
import { SubscriptionWizard } from "@/components/platform/subscription-wizard";
import { platformApi } from "@/lib/api/platform-client";
import { cn } from "@/lib/utils";
import { usePlatformSubscriptions } from "@/hooks/usePlatform";

export default function StrategySubscribePage() {
  const params = useParams();
  const code = String(params.code || "");
  const { data: subscriptions } = usePlatformSubscriptions();

  const { data: strategy, isLoading, isError } = useQuery({
    queryKey: ["platformStrategy", code],
    queryFn: () => platformApi.getStrategy(code),
    enabled: !!code,
  });

  const existingSubscriptionId = useMemo(() => {
    const sub = (subscriptions?.subscriptions ?? []).find((s: any) => s.strategy?.code === code);
    return sub?.id ?? null;
  }, [subscriptions, code]);

  if (isLoading) return <Skeleton className="h-64 w-full rounded-xl" />;
  if (isError || !strategy) {
    return <EmptyState title="Strategy not found" description={`No strategy with code "${code}" exists.`} />;
  }

  return (
    <div className="space-y-6">
      <Link
        href={`/strategies/${code}`}
        className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "h-8 px-2 text-xs w-fit")}
      >
        <ArrowLeft className="h-3.5 w-3.5 mr-1" />
        {strategy.name}
      </Link>

      <PageHeader
        title="Subscribe & Configure"
        description={
          existingSubscriptionId
            ? "Link another exchange account to your existing subscription with independent runtime controls."
            : "Complete the setup wizard — subscription is not activated until you confirm on the final step."
        }
        icon={Waypoints}
      />

      <SubscriptionWizard strategy={strategy} existingSubscriptionId={existingSubscriptionId} />
    </div>
  );
}
