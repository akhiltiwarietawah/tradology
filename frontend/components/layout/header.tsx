"use client";

import React, { useEffect, useState } from "react";
import { Activity, ShieldAlert, Wifi } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export function Header() {
  const [timeUtc, setTimeUtc] = useState<string>("");
  const [timeIst, setTimeIst] = useState<string>("");

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

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-card/80 backdrop-blur-md px-6 py-3">
      <div className="flex items-center justify-between">
        {/* Left: Brand / System Name */}
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
            <Activity className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-bold tracking-wider text-foreground uppercase">
                DELTA QUANT ENGINE
              </h1>
              <Badge variant="cyan" className="text-[10px] px-1.5 py-0">
                0DTE STRANGLE
              </Badge>
            </div>
            <p className="text-[11px] text-muted-foreground font-mono">
              BTC OPTIONS • DELTA INDIA • NATIVE BRACKET SL
            </p>
          </div>
        </div>

        {/* Right: Real-time clocks and quick status */}
        <div className="flex items-center gap-4">
          <div className="hidden sm:flex items-center gap-3 font-mono text-xs text-muted-foreground border-r border-border pr-4">
            <div>
              <span className="text-[10px] text-muted-foreground/60 mr-1">UTC:</span>
              <span className="text-foreground font-medium">{timeUtc || "--:--:-- UTC"}</span>
            </div>
            <div className="text-border">•</div>
            <div>
              <span className="text-[10px] text-muted-foreground/60 mr-1">IST:</span>
              <span className="text-foreground font-medium">{timeIst || "--:--:-- IST"}</span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Badge variant="outline" className="border-emerald-500/30 text-emerald-400 bg-emerald-500/5 text-xs py-1">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse mr-1.5" />
              SYSTEM ACTIVE
            </Badge>
          </div>
        </div>
      </div>
    </header>
  );
}
