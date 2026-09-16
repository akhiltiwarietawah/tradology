"use client";

import { Settings } from "lucide-react";
import { useSession } from "next-auth/react";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent } from "@/components/ui/card";

export default function SettingsPage() {
  const { data: session } = useSession();

  return (
    <div className="space-y-6 max-w-2xl">
      <PageHeader title="Settings" description="Profile and platform preferences." icon={Settings} />
      <Card className="bg-card/60 border-border/70">
        <CardContent className="p-5 space-y-3 text-sm">
          <div>
            <p className="text-muted-foreground text-xs">Signed in as</p>
            <p className="font-medium">{session?.user?.name || "Trader"}</p>
            <p className="text-xs text-muted-foreground font-mono">{session?.user?.email}</p>
          </div>
          <p className="text-xs text-muted-foreground pt-2 border-t border-border/50">
            Notification preferences, timezone, and API access controls will be added in a later phase.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
