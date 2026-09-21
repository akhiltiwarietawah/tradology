"use client";

import { Database, Lock, Radio } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/utils";
import type { SystemStatusResponse } from "@/lib/api/schemas";

interface EngineStatusBarProps {
  status?: SystemStatusResponse | null;
  isSafeHalt?: boolean;
  isRunning?: boolean;
  isExchangeConnected?: boolean;
  isWsStale?: boolean;
  isSynchronized?: boolean;
  isDbConnected?: boolean;
}

export function EngineStatusBar({
  status,
  isSafeHalt,
  isRunning,
  isExchangeConnected,
  isWsStale,
  isSynchronized,
  isDbConnected,
}: EngineStatusBarProps) {
  const engineStatus = status?.engine?.status || "STOPPED";
  const environment = status?.engine?.environment || "TESTNET";
  const dryRun = status?.engine?.dry_run ?? false;
  const killSwitch = status?.engine?.kill_switch ?? false;

  return (
    <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 bg-card/70 border border-border/80 rounded-lg p-3 px-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge
          variant={isSafeHalt ? "destructive" : isRunning ? "success" : "secondary"}
          className="text-xs px-2.5 py-1 font-mono font-bold"
        >
          <span
            className={`h-2 w-2 rounded-full mr-1.5 ${
              isSafeHalt ? "bg-rose-400 animate-ping" : isRunning ? "bg-emerald-400 animate-pulse" : "bg-slate-400"
            }`}
          />
          ENGINE {engineStatus}
        </Badge>
        <Badge variant={environment === "LIVE" ? "destructive" : "cyan"} className="text-[11px] font-mono px-2 py-0.5">
          {environment} • {dryRun ? "DRY RUN" : "LIVE ORDERS"}
        </Badge>
        <Badge variant={isExchangeConnected ? "success" : "destructive"} className="text-[11px] font-mono px-2 py-0.5">
          <Radio className="h-3 w-3 mr-1" />
          DELTA: {isExchangeConnected ? (isWsStale ? "REST FALLBACK" : "CONNECTED") : "OFFLINE"}
        </Badge>
        <Badge variant={isSynchronized ? "success" : "warning"} className="text-[11px] font-mono px-2 py-0.5">
          {isSynchronized ? "SYNCED" : "UNSYNCHRONIZED"}
        </Badge>
        <Badge variant={isDbConnected ? "info" : "secondary"} className="text-[11px] font-mono px-2 py-0.5">
          <Database className="h-3 w-3 mr-1" />
          POSTGRES: {isDbConnected ? "ONLINE" : "FALLBACK"}
        </Badge>
        {killSwitch && (
          <Badge variant="destructive" className="text-[11px] font-mono px-2 py-0.5">
            <Lock className="h-3 w-3 mr-1" />
            KILL SWITCH
          </Badge>
        )}
      </div>
      <div className="text-[11px] font-mono text-muted-foreground">
        Last sync:{" "}
        {status?.reconciliation?.last_reconciliation_time
          ? formatDateTime(status.reconciliation.last_reconciliation_time)
          : "--"}
      </div>
    </div>
  );
}
