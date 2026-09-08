"use client";

import React, { useEffect, useState } from "react";
import {
  ShieldCheck,
  ShieldAlert,
  Clock,
  CheckCircle2,
  TrendingUp,
  TrendingDown,
  Layers,
  ArrowRightLeft,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatDateTime } from "@/lib/utils";
import type { SystemStatusResponse } from "@/lib/api/schemas";

interface ActiveTradeProps {
  status?: SystemStatusResponse | null;
  isLoading?: boolean;
}

export function ActiveTrade({ status, isLoading }: ActiveTradeProps) {
  const [eodCountdown, setEodCountdown] = useState<string>("");

  useEffect(() => {
    const updateCountdown = () => {
      const now = new Date();
      // IST 17:15:00
      const istFormatter = new Intl.DateTimeFormat("en-US", {
        timeZone: "Asia/Kolkata",
        year: "numeric",
        month: "numeric",
        day: "numeric",
      });
      const parts = istFormatter.formatToParts(now);
      const year = parts.find((p) => p.type === "year")?.value;
      const month = parts.find((p) => p.type === "month")?.value?.padStart(2, "0");
      const day = parts.find((p) => p.type === "day")?.value?.padStart(2, "0");

      const exitTimeIst = new Date(`${year}-${month}-${day}T17:15:00+05:30`);
      const diffMs = exitTimeIst.getTime() - now.getTime();

      if (diffMs <= 0) {
        setEodCountdown("EOD PASSED (17:15 IST)");
      } else {
        const hours = Math.floor(diffMs / (1000 * 60 * 60));
        const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
        const seconds = Math.floor((diffMs % (1000 * 60)) / 1000);
        setEodCountdown(
          `${hours.toString().padStart(2, "0")}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`
        );
      }
    };

    updateCountdown();
    const interval = setInterval(updateCountdown, 1000);
    return () => clearInterval(interval);
  }, []);

  if (isLoading) {
    return (
      <Card className="bg-card/60 border-border/80">
        <CardHeader className="pb-3">
          <Skeleton className="h-5 w-48" />
        </CardHeader>
        <CardContent className="space-y-4">
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    );
  }

  const currentTrade = status?.current_trade;
  const isTradeActive = !!(currentTrade && currentTrade.trade_id && currentTrade.trade_state !== "COMPLETED");

  if (!isTradeActive) {
    return (
      <Card className="bg-card/40 border-border/60">
        <CardHeader className="py-4 border-b border-border/40">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Layers className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-xs font-semibold text-muted-foreground">
                Active Strategy Position
              </CardTitle>
            </div>
            <Badge variant="outline" className="text-[10px] text-muted-foreground border-border/60">
              IDLE
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="py-8 text-center">
          <div className="flex flex-col items-center justify-center space-y-2">
            <div className="h-10 w-10 rounded-full bg-secondary/50 flex items-center justify-center text-muted-foreground">
              <CheckCircle2 className="h-5 w-5" />
            </div>
            <h4 className="text-sm font-semibold text-foreground">No Open Strategy Positions</h4>
            <p className="text-xs text-muted-foreground max-w-sm">
              Engine is idle or waiting for next scheduled entry window (09:00 IST) on Delta Exchange India.
            </p>
            <div className="flex items-center gap-2 pt-2 text-[11px] font-mono text-muted-foreground/80">
              <Clock className="h-3.5 w-3.5" />
              <span>Next EOD Square-off Target: 17:15:00 IST</span>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  // Active Trade is present
  const ceBracketActive = currentTrade.ce_native_bracket_active ?? false;
  const peBracketActive = currentTrade.pe_native_bracket_active ?? false;
  const isBracketProtected = ceBracketActive && peBracketActive;

  const realizedPnl = currentTrade.total_realized_pnl ?? 0;

  const ceEntry = currentTrade.ce_entry_price ?? 0;
  const ceCurrent = currentTrade.ce_current_price ?? ceEntry;
  const ceQty = currentTrade.ce_quantity ?? 50;
  const ceUnrealized =
    currentTrade.ce_unrealized_pnl ??
    (ceEntry > 0 ? (ceEntry - ceCurrent) * ceQty * 0.001 : 0);

  const peEntry = currentTrade.pe_entry_price ?? 0;
  const peCurrent = currentTrade.pe_current_price ?? peEntry;
  const peQty = currentTrade.pe_quantity ?? 50;
  const peUnrealized =
    currentTrade.pe_unrealized_pnl ??
    (peEntry > 0 ? (peEntry - peCurrent) * peQty * 0.001 : 0);

  const unrealizedPnl =
    currentTrade.total_unrealized_pnl ?? ceUnrealized + peUnrealized;
  const totalTradePnl = realizedPnl + unrealizedPnl;

  const isUnrealizedProfitable = unrealizedPnl >= 0;

  return (
    <Card className="bg-card/70 border-border/80 shadow-md">
      <CardHeader className="py-3 px-4 border-b border-border/60 bg-secondary/20">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
            <h3 className="text-sm font-bold font-mono tracking-wider text-foreground uppercase">
              {currentTrade.strategy_name}
            </h3>
            <Badge variant="outline" className="font-mono text-[10px] text-muted-foreground">
              {currentTrade.trade_id}
            </Badge>
            <Badge
              variant={currentTrade.trade_state === "ACTIVE" ? "success" : "warning"}
              className="text-[10px]"
            >
              {currentTrade.trade_state}
            </Badge>

            {/* Prominent Live Unrealized P&L Badge */}
            <div
              className={`flex items-center gap-1 px-2.5 py-0.5 rounded border text-xs font-mono font-bold ${
                isUnrealizedProfitable
                  ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-400"
                  : "bg-rose-500/15 border-rose-500/40 text-rose-400"
              }`}
            >
              {isUnrealizedProfitable ? (
                <TrendingUp className="h-3.5 w-3.5 mr-0.5" />
              ) : (
                <TrendingDown className="h-3.5 w-3.5 mr-0.5" />
              )}
              <span>UNREALIZED P&amp;L:</span>
              <span>{formatCurrency(unrealizedPnl)}</span>
            </div>
          </div>

          <div className="flex items-center gap-3 text-xs font-mono">
            <div className="flex items-center gap-1.5 text-muted-foreground">
              <Clock className="h-3.5 w-3.5 text-cyan-400" />
              <span>EOD Square-off in:</span>
              <span className="text-foreground font-semibold">{eodCountdown}</span>
            </div>
            {isBracketProtected ? (
              <Badge variant="success" className="text-[10px] py-0.5">
                <ShieldCheck className="h-3 w-3 mr-1" />
                NATIVE SL ARMED
              </Badge>
            ) : (
              <Badge variant="destructive" className="text-[10px] py-0.5">
                <ShieldAlert className="h-3 w-3 mr-1 animate-pulse" />
                BRACKET WARNING
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-4 space-y-4">
        {/* Legs Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* CE Leg */}
          <div className="rounded-lg border border-border/70 bg-card/40 p-3.5 space-y-3">
            <div className="flex items-center justify-between border-b border-border/40 pb-2">
              <div className="flex items-center gap-2">
                <Badge variant="info" className="text-[11px] font-bold px-2 py-0">
                  CALL (CE)
                </Badge>
                <span className="text-xs font-mono font-medium text-foreground">
                  {currentTrade.ce_symbol || "--"}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={`text-xs font-mono font-bold ${
                    ceUnrealized >= 0 ? "text-emerald-400" : "text-rose-400"
                  }`}
                >
                  {ceUnrealized >= 0 ? "+" : ""}
                  {formatCurrency(ceUnrealized)}
                </span>
                <Badge
                  variant={currentTrade.ce_status === "OPEN" ? "success" : "outline"}
                  className="text-[10px]"
                >
                  {currentTrade.ce_status || "PENDING"}
                </Badge>
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
              <div>
                <span className="text-[10px] text-muted-foreground block">Strike</span>
                <span className="font-semibold text-foreground">
                  {currentTrade.ce_strike ? `$${currentTrade.ce_strike.toLocaleString()}` : "--"}
                </span>
              </div>
              <div>
                <span className="text-[10px] text-muted-foreground block">Entry Fill</span>
                <span className="font-semibold text-foreground">
                  {formatCurrency(currentTrade.ce_entry_price)}
                </span>
              </div>
              <div>
                <span className="text-[10px] text-muted-foreground block">Mark Price</span>
                <span className="font-semibold text-cyan-400">
                  {currentTrade.ce_current_price != null
                    ? formatCurrency(currentTrade.ce_current_price)
                    : currentTrade.ce_entry_price != null
                    ? formatCurrency(currentTrade.ce_entry_price)
                    : "--"}
                </span>
              </div>
              <div>
                <span className="text-[10px] text-muted-foreground block">Stop Loss (100%)</span>
                <span className="font-semibold text-rose-400">
                  {formatCurrency(currentTrade.ce_sl_price)}
                </span>
              </div>
            </div>

            <div className="pt-2 border-t border-border/40 flex items-center justify-between text-xs">
              <span className="text-[11px] text-muted-foreground">Exchange SL Protection:</span>
              {ceBracketActive ? (
                <div className="flex items-center gap-1.5 text-emerald-400 font-mono text-[11px]">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  <span>NATIVE BRACKET ({currentTrade.ce_bracket_order_id?.slice(-8) || "ACTIVE"})</span>
                </div>
              ) : (
                <div className="flex items-center gap-1.5 text-rose-400 font-mono text-[11px]">
                  <ShieldAlert className="h-3.5 w-3.5" />
                  <span>MISSING BRACKET</span>
                </div>
              )}
            </div>
          </div>

          {/* PE Leg */}
          <div className="rounded-lg border border-border/70 bg-card/40 p-3.5 space-y-3">
            <div className="flex items-center justify-between border-b border-border/40 pb-2">
              <div className="flex items-center gap-2">
                <Badge variant="cyan" className="text-[11px] font-bold px-2 py-0">
                  PUT (PE)
                </Badge>
                <span className="text-xs font-mono font-medium text-foreground">
                  {currentTrade.pe_symbol || "--"}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={`text-xs font-mono font-bold ${
                    peUnrealized >= 0 ? "text-emerald-400" : "text-rose-400"
                  }`}
                >
                  {peUnrealized >= 0 ? "+" : ""}
                  {formatCurrency(peUnrealized)}
                </span>
                <Badge
                  variant={currentTrade.pe_status === "OPEN" ? "success" : "outline"}
                  className="text-[10px]"
                >
                  {currentTrade.pe_status || "PENDING"}
                </Badge>
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
              <div>
                <span className="text-[10px] text-muted-foreground block">Strike</span>
                <span className="font-semibold text-foreground">
                  {currentTrade.pe_strike ? `$${currentTrade.pe_strike.toLocaleString()}` : "--"}
                </span>
              </div>
              <div>
                <span className="text-[10px] text-muted-foreground block">Entry Fill</span>
                <span className="font-semibold text-foreground">
                  {formatCurrency(currentTrade.pe_entry_price)}
                </span>
              </div>
              <div>
                <span className="text-[10px] text-muted-foreground block">Mark Price</span>
                <span className="font-semibold text-cyan-400">
                  {currentTrade.pe_current_price != null
                    ? formatCurrency(currentTrade.pe_current_price)
                    : currentTrade.pe_entry_price != null
                    ? formatCurrency(currentTrade.pe_entry_price)
                    : "--"}
                </span>
              </div>
              <div>
                <span className="text-[10px] text-muted-foreground block">Stop Loss (100%)</span>
                <span className="font-semibold text-rose-400">
                  {formatCurrency(currentTrade.pe_sl_price)}
                </span>
              </div>
            </div>

            <div className="pt-2 border-t border-border/40 flex items-center justify-between text-xs">
              <span className="text-[11px] text-muted-foreground">Exchange SL Protection:</span>
              {peBracketActive ? (
                <div className="flex items-center gap-1.5 text-emerald-400 font-mono text-[11px]">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  <span>NATIVE BRACKET ({currentTrade.pe_bracket_order_id?.slice(-8) || "ACTIVE"})</span>
                </div>
              ) : (
                <div className="flex items-center gap-1.5 text-rose-400 font-mono text-[11px]">
                  <ShieldAlert className="h-3.5 w-3.5" />
                  <span>MISSING BRACKET</span>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Footer Summary */}
        <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] font-mono text-muted-foreground pt-1 border-t border-border/30">
          <div>Entry: {formatDateTime(currentTrade.entry_timestamp)}</div>
          <div className="flex items-center gap-3">
            <span>
              Realized P&amp;L:{" "}
              <strong className={realizedPnl >= 0 ? "text-emerald-400" : "text-rose-400"}>
                {formatCurrency(realizedPnl)}
              </strong>
            </span>
            <span>
              Net Trade P&amp;L:{" "}
              <strong className={totalTradePnl >= 0 ? "text-emerald-400" : "text-rose-400"}>
                {formatCurrency(totalTradePnl)}
              </strong>
            </span>
          </div>
          <div>Contract: 0.001 BTC / Lot • Mark Price SL Trigger</div>
        </div>
      </CardContent>
    </Card>
  );
}
