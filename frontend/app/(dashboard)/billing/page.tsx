"use client";

import { CreditCard } from "lucide-react";
import { PageHeader, EmptyState } from "@/components/ui/page-header";
import { usePlatformSubscriptions } from "@/hooks/usePlatform";

export default function BillingPage() {
  const { data } = usePlatformSubscriptions();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Billing & Subscriptions"
        description="Strategy subscriptions are separate from exchange connections — one subscription can run on multiple accounts."
        icon={CreditCard}
      />
      {(data?.subscriptions || []).length > 0 ? (
        <div className="rounded-xl border border-border/70 bg-card/50 p-4 text-sm space-y-2">
          {(data?.subscriptions || []).map((sub: any) => (
            <div key={sub.id} className="flex justify-between font-mono text-xs">
              <span>{sub.strategy?.name}</span>
              <span>{sub.billing_plan} • {sub.status}</span>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState
          title="No billing records"
          description="Subscribe to strategies from the catalog. Payment integration can be added without changing the subscription ↔ account model."
        />
      )}
    </div>
  );
}
