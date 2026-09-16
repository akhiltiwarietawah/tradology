"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, RefreshCw, Wallet } from "lucide-react";
import { PageHeader, EmptyState } from "@/components/ui/page-header";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EquityCurveChart } from "@/components/charts/equity-curve-chart";
import {
  useAccountStrategies,
  usePlatformAccountDetail,
  usePlatformEquityCurve,
  useSyncExchangeAccount,
} from "@/hooks/usePlatform";
import {
  cn,
  formatCurrency,
  formatNumber,
  formatRelativeTime,
  healthBadgeVariant,
  runtimeStatusVariant,
} from "@/lib/utils";
import type { EquityRange } from "@/lib/api/platform-client";
import { StrategyRuntimeControls } from "@/components/platform/strategy-runtime-controls";

export default function AccountDetailPage() {
  const params = useParams();
  const accountId = String(params.id || "");
  const [range, setRange] = useState<EquityRange>("1M");

  const { data, isLoading, isError } = usePlatformAccountDetail(accountId);
  const { data: equityData, isLoading: equityLoading } = usePlatformEquityCurve(accountId, range);
  const { data: strategiesData } = useAccountStrategies(accountId);
  const syncAccount = useSyncExchangeAccount();

  const linkedStrategies = strategiesData?.strategies ?? [];

  if (isLoading) return <Skeleton className="h-64 w-full rounded-xl" />;
  if (isError || !data?.account) {
    return (
      <EmptyState
        title="Account not found"
        description="This exchange account does not exist or is not owned by you."
      />
    );
  }

  const account = data.account;
  const health = account.health_status || account.status || account.connection_status;

  return (
    <div className="space-y-6">
      <Link
        href="/accounts"
        className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "h-8 px-2 text-xs w-fit")}
      >
        <ArrowLeft className="h-3.5 w-3.5 mr-1" />
        Accounts
      </Link>

      <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-4">
        <PageHeader
          title={account.label}
          description={`${account.exchange.toUpperCase()} • ${account.is_testnet ? "Testnet" : "Live"}`}
          icon={Wallet}
        />
        <div className="flex items-center gap-2">
          <Badge variant={healthBadgeVariant(health)}>{health}</Badge>
          <span className="text-[11px] text-muted-foreground font-mono">
            Last synced {formatRelativeTime(account.last_synced_at || account.last_sync_at)}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={syncAccount.isPending}
            onClick={() => syncAccount.mutate(accountId)}
          >
            <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${syncAccount.isPending ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      {account.last_error && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-xs text-amber-300">
          Sync issue: {account.last_error}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {[
          ["Equity", formatCurrency(account.equity ?? account.balance ?? 0)],
          ["Available Balance", formatCurrency(account.available_balance ?? 0)],
          [
            "Unrealized P&L",
            formatCurrency(account.unrealized_pnl ?? 0),
            (account.unrealized_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400",
          ],
          [
            "Realized P&L",
            formatCurrency(account.realized_pnl ?? 0),
            (account.realized_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400",
          ],
        ].map(([label, value, tone]) => (
          <Card key={label as string} className="bg-card/60 border-border/70">
            <CardContent className="p-4">
              <p className="text-[11px] text-muted-foreground uppercase">{label}</p>
              <p className={`text-lg font-mono font-semibold mt-1 ${tone || ""}`}>{value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <EquityCurveChart
        title="Account Equity"
        currency={account.currency || equityData?.currency || "USD"}
        points={equityData?.points ?? []}
        range={range}
        onRangeChange={setRange}
        isLoading={equityLoading}
      />

      <Card className="bg-card/60 border-border/70">
        <CardContent className="p-0">
          <div className="px-4 py-3 border-b border-border/60">
            <h3 className="text-xs font-semibold uppercase tracking-wider">Open Positions</h3>
          </div>
          {!data.positions.length ? (
            <div className="p-6 text-xs text-muted-foreground text-center">No open positions</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-muted-foreground border-b border-border/50">
                    {["Symbol", "Side", "Size", "Entry", "Mark", "P&L", "Leverage"].map((h) => (
                      <th key={h} className="text-left font-medium px-4 py-2.5">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.positions.map((pos, idx) => (
                    <tr key={`${pos.symbol}-${idx}`} className="border-b border-border/30 hover:bg-secondary/20">
                      <td className="px-4 py-2.5 font-mono">{pos.symbol}</td>
                      <td className="px-4 py-2.5">
                        <Badge variant={pos.side?.toLowerCase() === "long" ? "success" : "destructive"} className="text-[10px]">
                          {pos.side}
                        </Badge>
                      </td>
                      <td className="px-4 py-2.5 font-mono">{formatNumber(pos.quantity, 4)}</td>
                      <td className="px-4 py-2.5 font-mono">{formatNumber(pos.entry_price)}</td>
                      <td className="px-4 py-2.5 font-mono">{formatNumber(pos.mark_price)}</td>
                      <td
                        className={`px-4 py-2.5 font-mono ${
                          (pos.unrealized_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"
                        }`}
                      >
                        {formatCurrency(pos.unrealized_pnl ?? 0)}
                      </td>
                      <td className="px-4 py-2.5 font-mono">{pos.leverage ? `${pos.leverage}x` : "--"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {!!data.orders.length && (
        <Card className="bg-card/60 border-border/70">
          <CardContent className="p-0">
            <div className="px-4 py-3 border-b border-border/60">
              <h3 className="text-xs font-semibold uppercase tracking-wider">Open Orders</h3>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-muted-foreground border-b border-border/50">
                    {["Symbol", "Side", "Type", "Qty", "Price", "Status"].map((h) => (
                      <th key={h} className="text-left font-medium px-4 py-2.5">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.orders.map((order) => (
                    <tr key={order.exchange_order_id} className="border-b border-border/30">
                      <td className="px-4 py-2.5 font-mono">{order.symbol}</td>
                      <td className="px-4 py-2.5">{order.side}</td>
                      <td className="px-4 py-2.5">{order.order_type || "--"}</td>
                      <td className="px-4 py-2.5 font-mono">{formatNumber(order.quantity, 4)}</td>
                      <td className="px-4 py-2.5 font-mono">{formatNumber(order.price)}</td>
                      <td className="px-4 py-2.5">{order.status || "--"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      <Card className="bg-card/60 border-border/70">
        <CardContent className="p-0">
          <div className="px-4 py-3 border-b border-border/60 flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wider">Strategies Running On This Account</h3>
            <Link href="/my-strategies" className="text-[10px] text-emerald-400 hover:underline">
              Manage all
            </Link>
          </div>
          {!linkedStrategies.length ? (
            <div className="p-6 text-xs text-muted-foreground text-center space-y-2">
              <p>No strategies linked to this account yet.</p>
              <Link href="/strategies" className="text-emerald-400 underline">
                Subscribe to a strategy
              </Link>
            </div>
          ) : (
            <div className="divide-y divide-border/40">
              {linkedStrategies.map((link: any) => (
                <div key={link.strategy_account_id} className="px-4 py-4 space-y-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-start gap-3">
                      <span className="text-muted-foreground font-mono text-xs mt-0.5">├──</span>
                      <div>
                        <Link
                          href={`/strategies/${link.strategy_code}`}
                          className="text-sm font-medium hover:text-emerald-300"
                        >
                          {link.strategy_name}
                        </Link>
                        <div className="flex items-center gap-2 mt-1 flex-wrap">
                          <Badge variant={runtimeStatusVariant(link.runtime_status)} className="text-[10px]">
                            {link.runtime_status}
                          </Badge>
                          <Badge variant="outline" className="text-[10px]">
                            {link.execution_mode}
                          </Badge>
                          <span className="text-[10px] text-muted-foreground">{link.strategy_code}</span>
                        </div>
                      </div>
                    </div>
                    <Link
                      href={`/execution/${link.strategy_account_id}`}
                      className="text-[10px] text-muted-foreground hover:text-emerald-300"
                    >
                      Runtime detail
                    </Link>
                  </div>
                  <StrategyRuntimeControls
                    strategyAccountId={link.strategy_account_id}
                    executionMode={link.execution_mode || "PAPER"}
                    tradingEnabled={!!link.trading_enabled}
                    runtimeStatus={link.runtime_status || "STOPPED"}
                    compact
                  />
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
