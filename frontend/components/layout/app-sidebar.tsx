"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BarChart3,
  CandlestickChart,
  CreditCard,
  LayoutDashboard,
  Layers,
  LineChart,
  ListOrdered,
  Settings,
  Wallet,
  Waypoints,
} from "lucide-react";
import { cn } from "@/lib/utils";

const primaryNav = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/engine/eth", label: "Renko ETH", icon: CandlestickChart },
  { href: "/engine/sol", label: "Renko SOL", icon: CandlestickChart },
  { href: "/engine/xrp", label: "Renko XRP", icon: CandlestickChart },
  { href: "/engine/strangle", label: "BTC Strangle", icon: Layers },
  { href: "/performance", label: "Performance", icon: LineChart },
  { href: "/trades", label: "Trades", icon: Activity },
  { href: "/orders", label: "Orders", icon: ListOrdered },
];

const catalogNav = [
  { href: "/strategies", label: "Catalog", icon: Waypoints },
  { href: "/my-strategies", label: "My Strategies", icon: Layers },
  { href: "/accounts", label: "Accounts", icon: Wallet },
];

const secondaryNav = [
  { href: "/billing", label: "Billing", icon: CreditCard },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function AppSidebar() {
  const pathname = usePathname();

  const renderLink = (item: (typeof primaryNav)[number]) => {
    const active =
      item.href === "/"
        ? pathname === "/"
        : pathname === item.href || pathname.startsWith(`${item.href}/`);
    const Icon = item.icon;
    return (
      <Link
        key={item.href}
        href={item.href}
        className={cn(
          "flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-xs font-medium transition-all",
          active
            ? "bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 shadow-sm"
            : "text-muted-foreground hover:text-foreground hover:bg-secondary/50 border border-transparent",
        )}
      >
        <Icon className="h-4 w-4 shrink-0" />
        {item.label}
      </Link>
    );
  };

  return (
    <aside className="hidden lg:flex w-60 shrink-0 flex-col border-r border-border/70 bg-card/40 backdrop-blur-xl">
      <div className="p-5 border-b border-border/60">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-400">
            <BarChart3 className="h-4 w-4" />
          </div>
          <div>
            <p className="text-sm font-bold tracking-wider uppercase">Tradology</p>
            <p className="text-[10px] text-muted-foreground font-mono">Trading Terminal</p>
          </div>
        </div>
      </div>

      <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
        <p className="px-3 pb-1 text-[10px] uppercase tracking-widest text-muted-foreground/70">Live engine</p>
        {primaryNav.map(renderLink)}
        <div className="pt-4 pb-1">
          <p className="px-3 pb-1 text-[10px] uppercase tracking-widest text-muted-foreground/70">Platform</p>
        </div>
        {catalogNav.map(renderLink)}
        <div className="pt-4 pb-1">
          <p className="px-3 pb-1 text-[10px] uppercase tracking-widest text-muted-foreground/70">Account</p>
        </div>
        {secondaryNav.map(renderLink)}
      </nav>
    </aside>
  );
}
