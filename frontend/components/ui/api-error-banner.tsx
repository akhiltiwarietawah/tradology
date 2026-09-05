"use client";

import React from "react";
import { AlertTriangle, RefreshCw, WifiOff } from "lucide-react";
import { Button } from "./button";

export interface ApiErrorBannerProps {
  title?: string;
  message?: string;
  isNetworkError?: boolean;
  onRetry?: () => void;
}

export function ApiErrorBanner({
  title = "Backend Connection Offline",
  message = "Cannot communicate with the FastAPI trading engine. Please verify that the engine process is running on port 8000.",
  isNetworkError = true,
  onRetry,
}: ApiErrorBannerProps) {
  return (
    <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-destructive">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          {isNetworkError ? (
            <WifiOff className="h-5 w-5 mt-0.5 shrink-0 text-rose-400" />
          ) : (
            <AlertTriangle className="h-5 w-5 mt-0.5 shrink-0 text-amber-400" />
          )}
          <div>
            <h4 className="text-sm font-semibold tracking-wide text-foreground">
              {title}
            </h4>
            <p className="text-xs text-muted-foreground mt-0.5">
              {message}
            </p>
          </div>
        </div>

        {onRetry && (
          <Button
            variant="outline"
            size="sm"
            onClick={onRetry}
            className="shrink-0 border-destructive/30 hover:bg-destructive/20 text-foreground text-xs"
          >
            <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
            Retry
          </Button>
        )}
      </div>
    </div>
  );
}
