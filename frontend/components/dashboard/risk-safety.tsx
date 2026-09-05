"use client";

import React from "react";
import {
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  Radio,
  Database,
  Lock,
  Zap,
  Activity,
  Bell,
  Clock,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime } from "@/lib/utils";
import type { SystemStatusResponse } from "@/lib/api/schemas";

interface RiskSafetyProps {
  status?: SystemStatusResponse | null;
  isLoading?: boolean;
}

export function RiskSafety({ status, isLoading }: RiskSafetyProps) {
  if (isLoading) {
    return (
      <Card className="bg-card/60 border-border/80">
        <CardHeader>
          <Skeleton className="h-5 w-40" />
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-32 w-full" />
        </CardContent>
      </Card>
    );
  }

  const engineStatus = status?.engine?.status || "STOPPED";
  const isSafeHalt = engineStatus === "SAFE_HALT";
  const isKillSwitchActive = status?.engine?.kill_switch ?? false;
  const isDryRun = status?.engine?.dry_run ?? false;
  const isReconciled = status?.reconciliation?.is_synchronized ?? false;
  const reconcileStatus = status?.reconciliation?.status ?? "PENDING";
  const discrepancy = status?.reconciliation?.latest_discrepancy;
  const isWsConnected = status?.exchange?.ws_connected ?? false;
  const isWsStale = status?.exchange?.ws_stale ?? false;
  const isRestConnected = status?.exchange?.rest_connected ?? false;
  const isDbConnected = status?.database?.connected ?? false;
  const alerts = status?.alerts?.recent_alerts ?? [];

  return (
    <Card className="bg-card/60 border-border/80 shadow-sm">
      <CardHeader className="py-3.5 px-4 border-b border-border/60 bg-secondary/10">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-emerald-400" />
            <CardTitle className="text-xs font-semibold text-foreground uppercase tracking-wider">
              Risk &amp; Safety Control Monitor
            </CardTitle>
          </div>
          <Badge
            variant={isSafeHalt ? "destructive" : "success"}
            className="text-[10px] font-mono"
          >
            {isSafeHalt ? "EMERGENCY HALT" : "SYSTEM PROTECTED"}
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="p-4 space-y-4">
        {/* SAFE_HALT Prominent Alert Banner */}
        {isSafeHalt && (
          <div className="rounded-lg border-2 border-rose-500 bg-rose-500/15 p-4 animate-pulse">
            <div className="flex items-start gap-3">
              <ShieldAlert className="h-6 w-6 text-rose-400 shrink-0 mt-0.5" />
              <div>
                <h4 className="text-sm font-bold text-rose-300 uppercase tracking-wide">
                  🚨 SAFE_HALT ACTIVE: ALL NEW TRADING BLOCKED
                </h4>
                <p className="text-xs text-rose-200 mt-1">
                  Engine entered fail-safe halt mode. Orders are blocked and existing manual positions remain isolated.
                </p>
                {discrepancy && (
                  <div className="mt-2 text-xs font-mono bg-background/80 p-2 rounded border border-rose-500/30 text-rose-300">
                    Discrepancy: {typeof discrepancy === "object" ? JSON.stringify(discrepancy) : String(discrepancy)}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Safety KPI Indicators */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs font-mono">
          {/* 1. Reconciliation */}
          <div className="rounded border border-border/60 bg-secondary/20 p-2.5 space-y-1">
            <div className="flex items-center justify-between text-muted-foreground text-[10px]">
              <span>RECONCILIATION</span>
              <Activity className="h-3 w-3" />
            </div>
            <div className="flex items-center gap-1.5">
              <span
                className={`h-2 w-2 rounded-full ${isReconciled ? "bg-emerald-400" : "bg-rose-400 animate-ping"}`}
              />
              <span className="font-semibold text-foreground text-xs">{reconcileStatus}</span>
            </div>
            <div className="text-[9px] text-muted-foreground truncate">
              {status?.reconciliation?.last_reconciliation_time
                ? formatDateTime(status.reconciliation.last_reconciliation_time)
                : "Not yet run"}
            </div>
          </div>

          {/* 2. Exchange WebSockets */}
          <div className="rounded border border-border/60 bg-secondary/20 p-2.5 space-y-1">
            <div className="flex items-center justify-between text-muted-foreground text-[10px]">
              <span>DELTA WS FEED</span>
              <Radio className="h-3 w-3" />
            </div>
            <div className="flex items-center gap-1.5">
              <span
                className={`h-2 w-2 rounded-full ${isWsConnected && !isWsStale ? "bg-emerald-400" : "bg-amber-400"}`}
              />
              <span className="font-semibold text-foreground text-xs">
                {isWsStale ? "STALE (REST ACTIVE)" : isWsConnected ? "STREAMING" : "DISCONNECTED"}
              </span>
            </div>
            <div className="text-[9px] text-muted-foreground truncate">
              {status?.exchange?.last_ws_tick_time
                ? formatDateTime(status.exchange.last_ws_tick_time)
                : "No ticks"}
            </div>
          </div>

          {/* 3. Kill Switch & Dry Run */}
          <div className="rounded border border-border/60 bg-secondary/20 p-2.5 space-y-1">
            <div className="flex items-center justify-between text-muted-foreground text-[10px]">
              <span>KILL SWITCH</span>
              <Lock className="h-3 w-3" />
            </div>
            <div className="flex items-center gap-1.5">
              <span
                className={`h-2 w-2 rounded-full ${!isKillSwitchActive ? "bg-emerald-400" : "bg-rose-400"}`}
              />
              <span className="font-semibold text-foreground text-xs">
                {isKillSwitchActive ? "ENGAGED (HALT)" : "ARMED (NORMAL)"}
              </span>
            </div>
            <div className="text-[9px] text-muted-foreground">
              Mode: {isDryRun ? "DRY RUN" : "LIVE ORDERS"}
            </div>
          </div>

          {/* 4. Database Availability */}
          <div className="rounded border border-border/60 bg-secondary/20 p-2.5 space-y-1">
            <div className="flex items-center justify-between text-muted-foreground text-[10px]">
              <span>POSTGRESQL DB</span>
              <Database className="h-3 w-3" />
            </div>
            <div className="flex items-center gap-1.5">
              <span
                className={`h-2 w-2 rounded-full ${isDbConnected ? "bg-emerald-400" : "bg-amber-400"}`}
              />
              <span className="font-semibold text-foreground text-xs">
                {isDbConnected ? "SYNCHRONIZED" : "FALLBACK / OFF"}
              </span>
            </div>
            <div className="text-[9px] text-muted-foreground">
              Non-blocking audit log
            </div>
          </div>
        </div>

        {/* Recent Alerts Feed */}
        <div className="space-y-2 pt-1">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <Bell className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="font-semibold uppercase tracking-wider text-[11px]">Recent Operational Alerts</span>
            </div>
            <span className="text-[10px] font-mono">{alerts.length} events</span>
          </div>

          {alerts.length === 0 ? (
            <div className="rounded border border-border/40 bg-card/40 p-4 text-center text-xs text-muted-foreground">
              No recent alert events logged.
            </div>
          ) : (
            <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
              {alerts.slice(-5).reverse().map((alert, idx) => {
                let badgeVariant: "destructive" | "warning" | "success" | "info" = "info";
                if (alert.severity === "CRITICAL") badgeVariant = "destructive";
                else if (alert.severity === "WARNING") badgeVariant = "warning";
                else if (alert.severity === "SUCCESS") badgeVariant = "success";

                return (
                  <div
                    key={idx}
                    className="flex items-start justify-between gap-3 p-2.5 rounded bg-secondary/20 border border-border/40 text-xs font-mono"
                  >
                    <div className="flex items-start gap-2">
                      <Badge variant={badgeVariant} className="text-[9px] px-1.5 py-0 mt-0.5">
                        {alert.severity}
                      </Badge>
                      <div>
                        <span className="font-semibold text-foreground mr-1.5">
                          [{alert.event}]
                        </span>
                        <span className="text-muted-foreground text-[11px]">
                          {alert.message}
                        </span>
                      </div>
                    </div>
                    <div className="text-[10px] text-muted-foreground/70 shrink-0">
                      {formatDateTime(alert.timestamp)}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
