import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(value: number | null | undefined, currency: string = "$", decimals: number = 2): string {
  if (value === null || value === undefined || isNaN(value)) return "--";
  const absVal = Math.abs(value).toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  return value < 0 ? `-${currency}${absVal}` : `${currency}${absVal}`;
}

export function formatNumber(value: number | null | undefined, decimals: number = 2): string {
  if (value === null || value === undefined || isNaN(value)) return "--";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatPercent(value: number | null | undefined, decimals: number = 1): string {
  if (value === null || value === undefined || isNaN(value)) return "--";
  return `${value >= 0 ? "+" : ""}${value.toFixed(decimals)}%`;
}

export function formatDate(isoString: string | null | undefined): string {
  if (!isoString) return "--";
  try {
    const date = new Date(isoString);
    return date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return isoString;
  }
}

export function formatDateTime(isoString: string | null | undefined): string {
  if (!isoString) return "--";
  try {
    const date = new Date(isoString);
    return date.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return isoString;
  }
}

export function formatRelativeTime(isoString: string | null | undefined): string {
  if (!isoString) return "Never";
  try {
    const diffMs = Date.now() - new Date(isoString).getTime();
    const sec = Math.max(0, Math.floor(diffMs / 1000));
    if (sec < 60) return `${sec} sec ago`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min} min ago`;
    const hours = Math.floor(min / 60);
    if (hours < 24) return `${hours} hr ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  } catch {
    return isoString;
  }
}

export function healthBadgeVariant(
  status: string | null | undefined
): "success" | "warning" | "destructive" | "info" | "secondary" {
  const normalized = (status || "").toUpperCase();
  if (normalized === "CONNECTED" || normalized === "connected") return "success";
  if (normalized === "SYNCING") return "info";
  if (normalized === "DEGRADED") return "warning";
  if (normalized === "ERROR" || normalized === "error") return "destructive";
  return "secondary";
}

export function runtimeStatusVariant(
  status: string | null | undefined,
): "success" | "warning" | "destructive" | "info" | "secondary" {
  const normalized = (status || "").toUpperCase();
  if (normalized === "RUNNING") return "success";
  if (normalized === "STARTING" || normalized === "PAUSED") return "warning";
  if (normalized === "RECOVERY_REQUIRED" || normalized === "ERROR") return "destructive";
  if (normalized === "STOPPED") return "secondary";
  return "info";
}
