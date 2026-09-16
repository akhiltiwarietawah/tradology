"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useStrategyRuntimeControl } from "@/hooks/usePlatform";
import { formatRelativeTime, healthBadgeVariant } from "@/lib/utils";

interface StrategyRuntimeControlsProps {
  strategyAccountId: string;
  executionMode?: string;
  tradingEnabled?: boolean;
  runtimeStatus?: string;
  exchangeLabel?: string;
  lastHeartbeat?: string | null;
  compact?: boolean;
}

export function StrategyRuntimeControls({
  strategyAccountId,
  executionMode = "PAPER",
  tradingEnabled = false,
  runtimeStatus = "STOPPED",
  exchangeLabel,
  lastHeartbeat,
  compact = false,
}: StrategyRuntimeControlsProps) {
  const controls = useStrategyRuntimeControl();
  const [confirmLive, setConfirmLive] = useState(false);
  const isLive = executionMode === "LIVE";
  const isDryRun = executionMode === "LIVE_DRY_RUN";
  const isLiveMode = isLive || isDryRun;
  const isRunning = runtimeStatus === "RUNNING";
  const isPaused = runtimeStatus === "PAUSED";
  const pending =
    controls.start.isPending ||
    controls.stop.isPending ||
    controls.pause.isPending ||
    controls.resume.isPending ||
    controls.enableTrading.isPending;

  const handleEnableLive = async () => {
    if (!confirmLive) {
      setConfirmLive(true);
      return;
    }
    await controls.setMode.mutateAsync({ id: strategyAccountId, mode: "LIVE", confirmLive: true });
    setConfirmLive(false);
  };

  return (
    <div className={`space-y-3 ${compact ? "" : "rounded-lg border border-border/60 bg-secondary/10 p-4"}`}>
      <div className="flex flex-wrap items-center gap-2">
        {exchangeLabel && <span className="text-xs font-medium">{exchangeLabel}</span>}
        <Badge variant={isLive ? "destructive" : isDryRun ? "warning" : "info"} className="text-[10px]">
          {executionMode}
        </Badge>
        <Badge variant={healthBadgeVariant(runtimeStatus)} className="text-[10px]">
          {runtimeStatus}
        </Badge>
        <Badge variant={tradingEnabled ? "success" : "secondary"} className="text-[10px]">
          {tradingEnabled ? "Trading ON" : "Trading OFF"}
        </Badge>
      </div>

      {!compact && lastHeartbeat && (
        <p className="text-[10px] text-muted-foreground font-mono">
          Last heartbeat {formatRelativeTime(lastHeartbeat)}
        </p>
      )}

      {confirmLive && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-3 text-xs text-rose-200 space-y-1">
          <p className="font-semibold uppercase tracking-wide">Live Trading</p>
          {exchangeLabel && <p>Exchange: {exchangeLabel}</p>}
          <p>Mode: {isDryRun ? "LIVE DRY RUN (no orders submitted)" : "LIVE"}</p>
          <p className="text-rose-300/90">
            This strategy can place real orders using this account.
          </p>
          <div className="flex gap-2 mt-2">
            <Button size="sm" variant="destructive" disabled={pending} onClick={handleEnableLive}>
              Confirm LIVE
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={pending}
              onClick={async () => {
                await controls.setMode.mutateAsync({
                  id: strategyAccountId,
                  mode: "LIVE_DRY_RUN",
                  confirmLive: true,
                });
                setConfirmLive(false);
              }}
            >
              Use Dry Run
            </Button>
            <Button size="sm" variant="outline" onClick={() => setConfirmLive(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {!isRunning && !isPaused && (
          <Button size="sm" variant="outline" disabled={pending} onClick={() => controls.start.mutate(strategyAccountId)}>
            Start
          </Button>
        )}
        {isRunning && (
          <Button size="sm" variant="outline" disabled={pending} onClick={() => controls.pause.mutate(strategyAccountId)}>
            Pause
          </Button>
        )}
        {isPaused && (
          <Button size="sm" variant="outline" disabled={pending} onClick={() => controls.resume.mutate(strategyAccountId)}>
            Resume
          </Button>
        )}
        {(isRunning || isPaused) && (
          <Button size="sm" variant="outline" disabled={pending} onClick={() => controls.stop.mutate(strategyAccountId)}>
            Stop
          </Button>
        )}
        {!tradingEnabled ? (
          <Button
            size="sm"
            disabled={pending}
            onClick={() =>
              isLive
                ? controls.enableTrading.mutate({ id: strategyAccountId, confirmLive: true })
                : controls.enableTrading.mutate({ id: strategyAccountId })
            }
          >
            Enable Trading
          </Button>
        ) : (
          <Button size="sm" variant="outline" disabled={pending} onClick={() => controls.disableTrading.mutate(strategyAccountId)}>
            Disable Trading
          </Button>
        )}
        {!isLiveMode && !confirmLive && (
          <Button size="sm" variant="ghost" disabled={pending} onClick={() => setConfirmLive(true)}>
            Switch to LIVE
          </Button>
        )}
        {isLiveMode && (
          <Button
            size="sm"
            variant="ghost"
            disabled={pending}
            onClick={() => controls.setMode.mutate({ id: strategyAccountId, mode: "PAPER" })}
          >
            Switch to PAPER
          </Button>
        )}
        {runtimeStatus === "RECOVERY_REQUIRED" && (
          <Button
            size="sm"
            variant="outline"
            disabled={pending}
            onClick={() => controls.recover.mutate(strategyAccountId)}
          >
            Recover
          </Button>
        )}
        <Link
          href={`/execution/${strategyAccountId}`}
          className="inline-flex h-8 items-center rounded-md px-3 text-xs font-medium hover:bg-secondary/80"
        >
          Execution
        </Link>
      </div>
    </div>
  );
}
