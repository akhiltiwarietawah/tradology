"use client";

import { cn } from "@/lib/utils";
import { LayoutDashboard, Layers, CandlestickChart } from "lucide-react";

export type StrategyTab = "overview" | "strangle" | "renko";

interface StrategyTabsProps {
  activeTab: StrategyTab;
  onChange: (tab: StrategyTab) => void;
  renkoEnabled?: boolean;
}

const tabs: Array<{
  id: StrategyTab;
  label: string;
  shortLabel: string;
  icon: typeof LayoutDashboard;
}> = [
  { id: "overview", label: "Overview", shortLabel: "All", icon: LayoutDashboard },
  { id: "strangle", label: "BTC Short Strangle", shortLabel: "Strangle", icon: Layers },
  { id: "renko", label: "Renko Ichimoku", shortLabel: "Renko", icon: CandlestickChart },
];

export function StrategyTabs({
  activeTab,
  onChange,
  renkoEnabled = true,
}: StrategyTabsProps) {
  return (
    <div className="flex flex-wrap gap-2 p-1 rounded-xl bg-secondary/30 border border-border/60">
      {tabs.map((tab) => {
        if (tab.id === "renko" && !renkoEnabled) {
          return null;
        }

        const Icon = tab.icon;
        const isActive = activeTab === tab.id;

        return (
          <button
            key={tab.id}
            type="button"
            onClick={() => onChange(tab.id)}
            className={cn(
              "flex items-center gap-2 px-3 sm:px-4 py-2 rounded-lg text-xs font-semibold transition-all",
              isActive
                ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 shadow-sm"
                : "text-muted-foreground hover:text-foreground hover:bg-secondary/60 border border-transparent"
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{tab.label}</span>
            <span className="sm:hidden">{tab.shortLabel}</span>
          </button>
        );
      })}
    </div>
  );
}
