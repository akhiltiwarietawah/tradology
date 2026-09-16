"use client";

import { useParams } from "next/navigation";
import { Activity } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/ui/page-header";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { platformApi } from "@/lib/api/platform-client";

export default function ExecutionPage() {
  const params = useParams();
  const strategyAccountId = params?.id as string | undefined;

  const validation = useQuery({
    queryKey: ["validation", strategyAccountId],
    queryFn: () => platformApi.getValidationReport(strategyAccountId!),
    enabled: Boolean(strategyAccountId),
    refetchInterval: 15000,
  });

  const history = useQuery({
    queryKey: ["executionHistory", strategyAccountId],
    queryFn: () => platformApi.getExecutionHistory(strategyAccountId!),
    enabled: Boolean(strategyAccountId),
    refetchInterval: 15000,
  });

  if (!strategyAccountId) {
    return <p className="text-sm text-muted-foreground">Select a strategy account from My Strategies.</p>;
  }

  const report = validation.data;
  const stats = report?.stats;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Execution Activity"
        description="Live dry-run validation and order lifecycle history."
        icon={Activity}
      />

      {validation.isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : report ? (
        <div className="rounded-lg border border-border/60 bg-secondary/10 p-4 space-y-4">
          <div className="flex flex-wrap gap-2 items-center">
            <Badge variant={report.mode === "LIVE" ? "destructive" : report.mode === "LIVE_DRY_RUN" ? "warning" : "info"}>
              {report.mode}
            </Badge>
            <Badge variant={report.runtime_status === "RUNNING" ? "success" : "secondary"}>{report.runtime_status}</Badge>
            <Badge variant={report.reconciliation === "PASS" ? "success" : "destructive"}>
              Reconciliation: {report.reconciliation}
            </Badge>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-xs font-mono">
            <div>Signals: {stats?.signals_generated ?? 0}</div>
            <div>Would execute: {stats?.would_execute ?? 0}</div>
            <div>Risk rejected: {stats?.risk_rejected ?? 0}</div>
            <div>Duplicates blocked: {stats?.duplicate_prevented ?? 0}</div>
            <div>Stale data: {stats?.market_data_rejected ?? 0}</div>
            <div>Runtime errors: {stats?.runtime_errors ?? 0}</div>
          </div>
          <div className="text-[10px] text-muted-foreground space-y-1">
            <p>Last signal: {report.last_signal_at ?? "—"}</p>
            <p>Last order: {report.last_order_at ?? "—"}</p>
            <p>Last fill: {report.last_fill_at ?? "—"}</p>
          </div>
        </div>
      ) : null}

      <div className="rounded-lg border border-border/60 overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-secondary/20 text-muted-foreground">
            <tr>
              <th className="text-left p-2">Time</th>
              <th className="text-left p-2">Symbol</th>
              <th className="text-left p-2">Side</th>
              <th className="text-left p-2">Qty</th>
              <th className="text-left p-2">Status</th>
              <th className="text-left p-2">Mode</th>
            </tr>
          </thead>
          <tbody>
            {history.isLoading && (
              <tr>
                <td colSpan={6} className="p-4">
                  <Skeleton className="h-8 w-full" />
                </td>
              </tr>
            )}
            {(history.data?.orders ?? []).map((row: any) => (
              <tr key={row.client_order_id} className="border-t border-border/40">
                <td className="p-2 font-mono">{row.created_at?.slice(0, 19) ?? "—"}</td>
                <td className="p-2">{row.symbol}</td>
                <td className="p-2 uppercase">{row.side}</td>
                <td className="p-2">{row.quantity}</td>
                <td className="p-2">{row.status}</td>
                <td className="p-2">{row.execution_mode}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
