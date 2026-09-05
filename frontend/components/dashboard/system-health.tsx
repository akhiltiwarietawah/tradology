"use client";

import React from "react";
import { Server, Activity, Clock, Database, Radio, CheckCircle, AlertCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime } from "@/lib/utils";
import type { SystemStatusResponse } from "@/lib/api/schemas";

interface SystemHealthProps {
  status?: SystemStatusResponse | null;
  isLoading?: boolean;
}

export function SystemHealth({ status, isLoading }: SystemHealthProps) {
  if (isLoading) {
    return (
      <Card className="bg-card/60 border-border/80">
        <CardHeader className="pb-2">
          <Skeleton className="h-4 w-32" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-16 w-full" />
        </CardContent>
      </Card>
    );
  }

  const uptimeSec = status?.engine?.uptime_seconds ?? 0;
  const hours = Math.floor(uptimeSec / 3600);
  const minutes = Math.floor((uptimeSec % 3600) / 60);
  const seconds = Math.floor(uptimeSec % 60);
  const uptimeString = `${hours}h ${minutes}m ${seconds}s`;

  return (
    <Card className="bg-card/40 border-border/60 shadow-sm">
      <CardHeader className="py-2.5 px-4 border-b border-border/40 bg-secondary/10">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Server className="h-3.5 w-3.5 text-cyan-400" />
            <CardTitle className="text-xs font-semibold text-foreground uppercase tracking-wider">
              Connectivity &amp; Engine Watchdog
            </CardTitle>
          </div>
          <div className="text-[11px] font-mono text-muted-foreground">
            Uptime: <span className="text-foreground font-semibold">{uptimeString}</span>
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-3">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 text-xs font-mono">
          {/* Watchdog Heartbeat */}
          <div className="p-2 rounded bg-secondary/20 border border-border/40 space-y-0.5">
            <span className="text-[10px] text-muted-foreground block">WATCHDOG TICK</span>
            <span className="text-foreground font-semibold truncate block text-[11px]">
              {status?.watchdog?.last_heartbeat ? formatDateTime(status.watchdog.last_heartbeat) : "--"}
            </span>
          </div>

          {/* REST API Call */}
          <div className="p-2 rounded bg-secondary/20 border border-border/40 space-y-0.5">
            <span className="text-[10px] text-muted-foreground block">LAST REST REQ</span>
            <span className="text-foreground font-semibold truncate block text-[11px]">
              {status?.exchange?.last_rest_request_time ? formatDateTime(status.exchange.last_rest_request_time) : "--"}
            </span>
          </div>

          {/* WS Tick */}
          <div className="p-2 rounded bg-secondary/20 border border-border/40 space-y-0.5">
            <span className="text-[10px] text-muted-foreground block">LAST WS TICK</span>
            <span className="text-foreground font-semibold truncate block text-[11px]">
              {status?.exchange?.last_ws_tick_time ? formatDateTime(status.exchange.last_ws_tick_time) : "--"}
            </span>
          </div>

          {/* Reconciliation */}
          <div className="p-2 rounded bg-secondary/20 border border-border/40 space-y-0.5">
            <span className="text-[10px] text-muted-foreground block">LAST RECON SYNC</span>
            <span className="text-foreground font-semibold truncate block text-[11px]">
              {status?.reconciliation?.last_reconciliation_time ? formatDateTime(status.reconciliation.last_reconciliation_time) : "--"}
            </span>
          </div>

          {/* DB Persistence */}
          <div className="p-2 rounded bg-secondary/20 border border-border/40 space-y-0.5">
            <span className="text-[10px] text-muted-foreground block">LAST DB WRITE</span>
            <span className="text-foreground font-semibold truncate block text-[11px]">
              {status?.database?.last_db_operation ? formatDateTime(status.database.last_db_operation) : "--"}
            </span>
          </div>

          {/* Environment */}
          <div className="p-2 rounded bg-secondary/20 border border-border/40 space-y-0.5">
            <span className="text-[10px] text-muted-foreground block">ACTIVE ENV</span>
            <span className="text-cyan-400 font-semibold truncate block text-[11px]">
              {status?.engine?.environment || "TESTNET"} • {status?.engine?.dry_run ? "DRY RUN" : "LIVE"}
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
