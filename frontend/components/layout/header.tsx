"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Activity } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { UserMenu } from "@/components/auth/user-menu";
import { useSystemStatus } from "@/hooks/useSystemStatus";

export function Header() {
  const [timeUtc, setTimeUtc] = useState<string>("");
  const [timeIst, setTimeIst] = useState<string>("");
  const { isRunning, isSafeHalt, statusData } = useSystemStatus({ pollingIntervalMs: 10000 });

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTimeUtc(
        now.toLocaleTimeString("en-US", {
          timeZone: "UTC",
          hour12: false,
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }) + " UTC"
      );
      setTimeIst(
        now.toLocaleTimeString("en-US", {
          timeZone: "Asia/Kolkata",
          hour12: false,
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }) + " IST"
      );
    };

    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  const engineStatus = statusData?.engine?.status || "STOPPED";
  const renkoActive = (statusData?.strategies?.renko_ichimoku?.position ?? 0) !== 0;
  const strangleActive = !!(
    statusData?.current_trade?.trade_id &&
    statusData.current_trade.trade_state !== "COMPLETED"
  );

  return (
    <header className="sticky top-0 z-50 w-full border-b border-border/80 bg-card/85 backdrop-blur-xl">
      <div className="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 py-3">
        <div className="flex items-center justify-between gap-4">
          <Link href="/" className="flex items-center gap-3 group">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500/20 to-cyan-500/10 border border-emerald-500/30 text-emerald-400 group-hover:border-emerald-400/50 transition-colors">
              <Activity className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base font-bold tracking-wider text-foreground uppercase">
                  Tradology
                </h1>
                <Badge variant="cyan" className="text-[10px] px-1.5 py-0 hidden sm:inline-flex">
                  LIVE OPS
                </Badge>
              </div>
              <p className="text-[11px] text-muted-foreground font-mono hidden sm:block">
                BTC STRANGLE • RENKO ETH • DELTA INDIA
              </p>
            </div>
          </Link>

          <div className="flex items-center gap-3 sm:gap-5">
            <div className="hidden md:flex items-center gap-3 font-mono text-xs text-muted-foreground border-r border-border/60 pr-4">
              <div>
                <span className="text-[10px] text-muted-foreground/60 mr-1">UTC</span>
                <span className="text-foreground font-medium">{timeUtc || "--:--:--"}</span>
              </div>
              <div className="text-border">•</div>
              <div>
                <span className="text-[10px] text-muted-foreground/60 mr-1">IST</span>
                <span className="text-foreground font-medium">{timeIst || "--:--:--"}</span>
              </div>
            </div>

            <div className="hidden lg:flex items-center gap-2">
              {strangleActive && (
                <Badge variant="success" className="text-[10px] py-0.5">
                  STRANGLE LIVE
                </Badge>
              )}
              {renkoActive && (
                <Badge variant="info" className="text-[10px] py-0.5">
                  RENKO LIVE
                </Badge>
              )}
              <Badge
                variant={isSafeHalt ? "destructive" : isRunning ? "success" : "outline"}
                className="text-[10px] py-0.5"
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full mr-1.5 ${
                    isSafeHalt
                      ? "bg-rose-400 animate-ping"
                      : isRunning
                      ? "bg-emerald-400 animate-pulse"
                      : "bg-slate-400"
                  }`}
                />
                {engineStatus}
              </Badge>
            </div>

            <UserMenu />
          </div>
        </div>
      </div>
    </header>
  );
}
