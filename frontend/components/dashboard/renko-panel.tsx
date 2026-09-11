"use client";

import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  CandlestickChart,
  CheckCircle2,
  PauseCircle,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatDateTime } from "@/lib/utils";
import type { RenkoSnapshot } from "@/lib/api/schemas";

interface RenkoPanelProps {
  snapshot?: RenkoSnapshot | null;
  isLoading?: boolean;
}

function positionLabel(position?: number): { label: string; variant: "success" | "destructive" | "secondary" } {
  if (position === 1) return { label: "LONG", variant: "success" };
  if (position === -1) return { label: "SHORT", variant: "destructive" };
  return { label: "FLAT", variant: "secondary" };
}

export function RenkoPanel({ snapshot, isLoading }: RenkoPanelProps) {
  if (isLoading) {
    return (
      <Card className="bg-card/60 border-border/80">
        <CardHeader className="pb-3">
          <Skeleton className="h-5 w-48" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (!snapshot?.enabled) {
    return (
      <Card className="bg-card/40 border-border/60">
        <CardHeader className="py-4 border-b border-border/40">
          <div className="flex items-center gap-2">
            <CandlestickChart className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-xs font-semibold text-muted-foreground">
              Renko Ichimoku (ETH Perpetual)
            </CardTitle>
            <Badge variant="outline" className="text-[10px]">
              DISABLED
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="py-8 text-center text-xs text-muted-foreground">
          Renko Ichimoku strategy is not enabled on this engine instance.
        </CardContent>
      </Card>
    );
  }

  const pos = positionLabel(snapshot.position);
  const isOpen = snapshot.position !== 0;
  const isHalted = snapshot.orders_halted;

  if (!isOpen) {
    return (
      <Card className="bg-card/40 border-border/60">
        <CardHeader className="py-4 border-b border-border/40">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CandlestickChart className="h-4 w-4 text-violet-400" />
              <CardTitle className="text-xs font-semibold text-muted-foreground">
                Renko Ichimoku • {snapshot.symbol}
              </CardTitle>
            </div>
            <Badge variant="outline" className="text-[10px]">
              {pos.label}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="py-8 text-center">
          <div className="flex flex-col items-center space-y-2">
            <div className="h-10 w-10 rounded-full bg-secondary/50 flex items-center justify-center">
              <CheckCircle2 className="h-5 w-5 text-muted-foreground" />
            </div>
            <h4 className="text-sm font-semibold">No Open Renko Position</h4>
            <p className="text-xs text-muted-foreground max-w-md">
              Waiting for Ichimoku + Renko brick signal on {snapshot.configured_symbol || snapshot.symbol}.
              Bricks built: {snapshot.bricks ?? 0}
            </p>
            {isHalted && (
              <Badge variant="destructive" className="mt-2 text-[10px]">
                <PauseCircle className="h-3 w-3 mr-1" />
                ORDERS HALTED: {snapshot.halt_reason || "Unknown"}
              </Badge>
            )}
          </div>
        </CardContent>
      </Card>
    );
  }

  const isLong = snapshot.position === 1;

  return (
    <Card className="bg-card/70 border-border/80 shadow-md">
      <CardHeader className="py-3 px-4 border-b border-border/60 bg-violet-500/5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-violet-400 animate-pulse" />
            <h3 className="text-sm font-bold font-mono tracking-wider uppercase text-foreground">
              Renko Ichimoku
            </h3>
            <Badge variant="outline" className="font-mono text-[10px]">
              {snapshot.active_trade_id || snapshot.entry_order_id || "ACTIVE"}
            </Badge>
            <Badge variant={pos.variant} className="text-[10px]">
              {isLong ? (
                <ArrowUpRight className="h-3 w-3 mr-1" />
              ) : (
                <ArrowDownRight className="h-3 w-3 mr-1" />
              )}
              {pos.label}
            </Badge>
            <Badge variant="cyan" className="text-[10px] font-mono">
              {snapshot.symbol}
            </Badge>
          </div>

          {isHalted ? (
            <Badge variant="destructive" className="text-[10px]">
              <AlertTriangle className="h-3 w-3 mr-1" />
              HALTED
            </Badge>
          ) : (
            <Badge variant="success" className="text-[10px]">
              ORDERS LIVE
            </Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="p-4">
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 text-xs font-mono">
          <div>
            <span className="text-[10px] text-muted-foreground block">Entry Price</span>
            <span className="font-semibold text-foreground text-sm">
              {formatCurrency(snapshot.entry_price)}
            </span>
          </div>
          <div>
            <span className="text-[10px] text-muted-foreground block">Position Size</span>
            <span className="font-semibold text-foreground text-sm">
              {snapshot.position_size ?? "--"} contracts
            </span>
          </div>
          <div>
            <span className="text-[10px] text-muted-foreground block">Renko Bricks</span>
            <span className="font-semibold text-cyan-400 text-sm">{snapshot.bricks ?? 0}</span>
          </div>
          <div>
            <span className="text-[10px] text-muted-foreground block">Account</span>
            <span className="font-semibold text-foreground text-sm">{snapshot.account || "--"}</span>
          </div>
          <div>
            <span className="text-[10px] text-muted-foreground block">Instrument ID</span>
            <span className="font-semibold text-foreground text-sm">
              {snapshot.instrument_id ?? "--"}
            </span>
          </div>
          <div>
            <span className="text-[10px] text-muted-foreground block">Last Candle</span>
            <span className="font-semibold text-foreground text-[11px]">
              {snapshot.last_processed_candle_time
                ? formatDateTime(snapshot.last_processed_candle_time)
                : "--"}
            </span>
          </div>
        </div>

        {isHalted && snapshot.halt_reason && (
          <div className="mt-4 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-[11px] text-destructive">
            Halt reason: {snapshot.halt_reason}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
