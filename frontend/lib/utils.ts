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
