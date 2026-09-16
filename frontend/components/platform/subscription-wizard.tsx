"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { ApiErrorBanner } from "@/components/ui/api-error-banner";
import {
  buildRiskOverrides,
  getAllocationPct,
  getStrategyConfigSchema,
} from "@/lib/strategy-config-schema";
import type { PlatformExchangeAccount, PlatformStrategy } from "@/lib/api/platform-client";
import { cn, formatCurrency, healthBadgeVariant } from "@/lib/utils";
import {
  useLinkStrategyAccount,
  usePlatformAccounts,
  useSubscribeStrategy,
} from "@/hooks/usePlatform";

const STEPS = ["Trading Mode", "Parameters", "Select Account", "Review"] as const;
type ExecutionMode = "PAPER" | "LIVE" | "LIVE_DRY_RUN";

interface SubscriptionWizardProps {
  strategy: PlatformStrategy;
  existingSubscriptionId?: string | null;
}

export function SubscriptionWizard({ strategy, existingSubscriptionId }: SubscriptionWizardProps) {
  const router = useRouter();
  const subscribe = useSubscribeStrategy();
  const linkAccount = useLinkStrategyAccount();
  const { data: accountsData, isLoading: accountsLoading } = usePlatformAccounts();
  const accounts = accountsData?.accounts ?? [];

  const schema = useMemo(() => getStrategyConfigSchema(strategy.code), [strategy.code]);
  const [step, setStep] = useState(0);
  const [mode, setMode] = useState<ExecutionMode>("PAPER");
  const [confirmLive, setConfirmLive] = useState(false);
  const [selectedAccountId, setSelectedAccountId] = useState("");
  const [values, setValues] = useState<Record<string, string | number>>(() => {
    const initial: Record<string, string | number> = {};
    for (const field of schema.fields) {
      if (field.defaultValue !== undefined) initial[field.key] = field.defaultValue;
    }
    return initial;
  });

  const selectedAccount = accounts.find((a) => a.id === selectedAccountId);
  const compatibleAccounts = accounts.filter((a) =>
    (strategy.supported_exchanges || []).includes(a.exchange),
  );

  const error = (subscribe.error || linkAccount.error) as Error | null;
  const busy = subscribe.isPending || linkAccount.isPending;

  async function handleConfirm() {
    let subscriptionId = existingSubscriptionId;
    if (!subscriptionId) {
      const sub = await subscribe.mutateAsync(strategy.code);
      subscriptionId = sub.id;
    }
    if (!subscriptionId || !selectedAccountId) return;

    await linkAccount.mutateAsync({
      subscriptionId,
      exchangeAccountId: selectedAccountId,
      executionMode: mode,
      allocationPct: getAllocationPct(values),
      riskOverrides: buildRiskOverrides(strategy.code, values),
      confirmLive: mode !== "PAPER" ? confirmLive : false,
      status: "paused",
    });
    router.push("/my-strategies");
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-center gap-2 flex-wrap">
        {STEPS.map((label, idx) => (
          <div key={label} className="flex items-center gap-2">
            <div
              className={cn(
                "flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-semibold border",
                idx === step
                  ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                  : idx < step
                    ? "border-emerald-500/20 bg-emerald-500/5 text-emerald-400/80"
                    : "border-border/60 text-muted-foreground",
              )}
            >
              {idx < step ? <CheckCircle2 className="h-3.5 w-3.5" /> : idx + 1}
            </div>
            <span className={cn("text-xs", idx === step ? "text-foreground" : "text-muted-foreground")}>{label}</span>
            {idx < STEPS.length - 1 && <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/40 mx-1" />}
          </div>
        ))}
      </div>

      {error && <ApiErrorBanner message={error.message} />}

      {step === 0 && (
        <Card className="bg-card/60 border-border/70">
          <CardContent className="p-5 space-y-4">
            <p className="text-sm text-muted-foreground">Choose how this strategy will execute on your linked account.</p>
            <div className="grid gap-3">
              <ModeOption
                active={mode === "PAPER"}
                title="Paper"
                description="Simulated execution — recommended default. No exchange orders."
                onClick={() => setMode("PAPER")}
                recommended
              />
              <ModeOption
                active={mode === "LIVE_DRY_RUN"}
                title="Live Dry Run"
                description="Full live pipeline validation without submitting orders to the exchange."
                onClick={() => setMode("LIVE_DRY_RUN")}
              />
              <ModeOption
                active={mode === "LIVE"}
                title="Live"
                description="Real exchange execution. Requires server-side live flags and explicit confirmation."
                onClick={() => setMode("LIVE")}
                warning
              />
            </div>
            {mode !== "PAPER" && (
              <label className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs cursor-pointer">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={confirmLive}
                  onChange={(e) => setConfirmLive(e.target.checked)}
                />
                <span>
                  I understand the risks of {mode === "LIVE" ? "live trading" : "live dry-run validation"} and accept
                  that Tradology will not enable live submission unless server flags allow it.
                </span>
              </label>
            )}
          </CardContent>
        </Card>
      )}

      {step === 1 && (
        <Card className="bg-card/60 border-border/70">
          <CardContent className="p-5 space-y-4">
            <p className="text-sm text-muted-foreground">Configure strategy-specific parameters supported by the backend.</p>
            <div className="grid gap-4 md:grid-cols-2">
              {schema.fields.map((field) => (
                <div key={field.key} className="space-y-1.5">
                  <label className="text-xs font-medium">{field.label}</label>
                  {field.type === "select" ? (
                    <Select
                      value={String(values[field.key] ?? "")}
                      onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}
                    >
                      {(field.options || []).map((opt) => (
                        <option key={String(opt.value)} value={String(opt.value)}>
                          {opt.label}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <Input
                      type={field.type === "number" ? "number" : "text"}
                      min={field.min}
                      max={field.max}
                      step={field.step}
                      value={values[field.key] ?? ""}
                      onChange={(e) =>
                        setValues((v) => ({
                          ...v,
                          [field.key]: field.type === "number" ? Number(e.target.value) : e.target.value,
                        }))
                      }
                    />
                  )}
                  {field.description && <p className="text-[10px] text-muted-foreground">{field.description}</p>}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {step === 2 && (
        <Card className="bg-card/60 border-border/70">
          <CardContent className="p-5 space-y-4">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm text-muted-foreground">Select a connected exchange account for this strategy.</p>
              <Link href="/connect" className="text-xs text-emerald-400 hover:underline">
                Connect another account
              </Link>
            </div>
            {accountsLoading && <p className="text-xs text-muted-foreground">Loading accounts...</p>}
            {!accountsLoading && compatibleAccounts.length === 0 && (
              <div className="rounded-lg border border-dashed border-border/70 p-6 text-center text-xs text-muted-foreground">
                No compatible accounts for {strategy.supported_exchanges?.join(", ") || "this strategy"}.
                <div className="mt-3">
                  <Link href="/connect">
                    <Button size="sm">Connect Exchange</Button>
                  </Link>
                </div>
              </div>
            )}
            <div className="grid gap-3">
              {compatibleAccounts.map((account) => (
                <AccountPickCard
                  key={account.id}
                  account={account}
                  selected={selectedAccountId === account.id}
                  onSelect={() => setSelectedAccountId(account.id)}
                />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {step === 3 && (
        <Card className="bg-card/60 border-border/70">
          <CardContent className="p-5 space-y-4 text-sm">
            <ReviewRow label="Strategy" value={strategy.name} />
            <ReviewRow label="Execution mode" value={mode} />
            <ReviewRow label="Account" value={selectedAccount ? `${selectedAccount.label} (${selectedAccount.exchange})` : "—"} />
            <ReviewRow label="Allocation" value={`${getAllocationPct(values)}%`} />
            <div>
              <p className="text-[11px] uppercase tracking-wider text-muted-foreground mb-2">Parameters</p>
              <div className="rounded-md border border-border/50 bg-background/30 p-3 font-mono text-xs space-y-1">
                {Object.entries(buildRiskOverrides(strategy.code, values)).map(([k, v]) => (
                  <div key={k}>
                    {k}: {String(v)}
                  </div>
                ))}
                {!Object.keys(buildRiskOverrides(strategy.code, values)).length && (
                  <span className="text-muted-foreground">Default backend parameters</span>
                )}
              </div>
            </div>
            {mode !== "PAPER" && (
              <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-200">
                <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                Live modes require explicit confirmation and remain blocked until server live flags are enabled by an operator.
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <div className="flex items-center justify-between">
        <Button variant="outline" size="sm" disabled={step === 0 || busy} onClick={() => setStep((s) => s - 1)}>
          <ChevronLeft className="h-4 w-4 mr-1" />
          Back
        </Button>
        {step < STEPS.length - 1 ? (
          <Button
            size="sm"
            disabled={
              (step === 0 && mode !== "PAPER" && !confirmLive) ||
              (step === 2 && !selectedAccountId)
            }
            onClick={() => setStep((s) => s + 1)}
          >
            Continue
            <ChevronRight className="h-4 w-4 ml-1" />
          </Button>
        ) : (
          <Button
            size="sm"
            disabled={busy || !selectedAccountId || (mode !== "PAPER" && !confirmLive)}
            onClick={() => handleConfirm().catch(() => undefined)}
          >
            {busy ? "Subscribing..." : "Confirm & Subscribe"}
          </Button>
        )}
      </div>
    </div>
  );
}

function ModeOption({
  active,
  title,
  description,
  onClick,
  recommended,
  warning,
}: {
  active: boolean;
  title: string;
  description: string;
  onClick: () => void;
  recommended?: boolean;
  warning?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-lg border p-4 text-left transition-colors",
        active ? "border-emerald-500/40 bg-emerald-500/5" : "border-border/60 hover:border-border",
      )}
    >
      <div className="flex items-center gap-2">
        <p className="text-sm font-medium">{title}</p>
        {recommended && (
          <Badge variant="success" className="text-[10px]">
            Recommended
          </Badge>
        )}
        {warning && (
          <Badge variant="destructive" className="text-[10px]">
            High risk
          </Badge>
        )}
      </div>
      <p className="text-xs text-muted-foreground mt-1">{description}</p>
    </button>
  );
}

function AccountPickCard({
  account,
  selected,
  onSelect,
}: {
  account: PlatformExchangeAccount;
  selected: boolean;
  onSelect: () => void;
}) {
  const health = account.health_status || account.connection_status;
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "w-full rounded-lg border p-4 text-left transition-colors",
        selected ? "border-emerald-500/40 bg-emerald-500/5" : "border-border/60 hover:border-border",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium">{account.label}</p>
          <p className="text-[10px] uppercase text-muted-foreground">{account.exchange}</p>
        </div>
        <div className="text-right">
          <Badge variant={healthBadgeVariant(health)} className="text-[10px] mb-1">
            {health || account.connection_status}
          </Badge>
          <p className="text-sm font-mono font-semibold">{formatCurrency(account.equity ?? account.balance ?? 0)}</p>
        </div>
      </div>
    </button>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-border/40 pb-2">
      <span className="text-muted-foreground text-xs uppercase tracking-wider">{label}</span>
      <span className="font-medium text-sm">{value}</span>
    </div>
  );
}
