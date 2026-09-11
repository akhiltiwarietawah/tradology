"use client";

import { Suspense, useEffect } from "react";
import { useSession } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Activity,
  BarChart3,
  Lock,
  ShieldCheck,
  TrendingUp,
} from "lucide-react";
import { GoogleSignInButton } from "@/components/auth/google-sign-in-button";
import { Badge } from "@/components/ui/badge";

function LoginContent() {
  const { status } = useSession();
  const router = useRouter();
  const searchParams = useSearchParams();
  const callbackUrl = searchParams.get("callbackUrl") || "/";
  const error = searchParams.get("error");

  useEffect(() => {
    if (status === "authenticated") {
      router.replace(callbackUrl);
    }
  }, [status, router, callbackUrl]);

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-background">
      <div className="relative hidden lg:flex flex-col justify-between overflow-hidden p-10">
        <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/10 via-cyan-500/5 to-violet-500/10" />
        <div className="absolute -top-24 -left-24 h-72 w-72 rounded-full bg-emerald-500/10 blur-3xl" />
        <div className="absolute bottom-0 right-0 h-96 w-96 rounded-full bg-cyan-500/10 blur-3xl" />

        <div className="relative z-10 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-500/15 border border-emerald-500/30 text-emerald-400">
            <Activity className="h-6 w-6" />
          </div>
          <div>
            <p className="text-lg font-bold tracking-wider uppercase">Tradology</p>
            <p className="text-xs text-muted-foreground font-mono">Quantitative Trading Platform</p>
          </div>
        </div>

        <div className="relative z-10 space-y-8 max-w-lg">
          <div>
            <h1 className="text-4xl font-bold tracking-tight text-foreground leading-tight">
              Institutional-grade trading operations, simplified.
            </h1>
            <p className="mt-4 text-muted-foreground text-sm leading-relaxed">
              Monitor live BTC 0DTE strangle positions, Renko Ichimoku ETH perpetuals,
              risk controls, and PostgreSQL-backed trade history — all in one secure dashboard.
            </p>
          </div>

          <div className="grid gap-3">
            {[
              {
                icon: ShieldCheck,
                title: "Exchange-native risk controls",
                desc: "Native bracket SL, reconciliation, and kill-switch visibility",
              },
              {
                icon: TrendingUp,
                title: "Multi-strategy monitoring",
                desc: "Short strangle + Renko Ichimoku with live P&L and trade history",
              },
              {
                icon: BarChart3,
                title: "Performance analytics",
                desc: "Equity curve, drawdown, daily and monthly aggregates",
              },
            ].map((item) => (
              <div
                key={item.title}
                className="flex items-start gap-3 rounded-lg border border-border/50 bg-card/40 p-4 backdrop-blur-sm"
              >
                <item.icon className="h-5 w-5 text-emerald-400 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-semibold text-foreground">{item.title}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{item.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="relative z-10 flex flex-wrap gap-2">
          <Badge variant="success" className="text-[10px]">
            DELTA EXCHANGE INDIA
          </Badge>
          <Badge variant="cyan" className="text-[10px]">
            LIVE + TESTNET
          </Badge>
          <Badge variant="outline" className="text-[10px]">
            POSTGRES PERSISTENCE
          </Badge>
        </div>
      </div>

      <div className="flex items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-md space-y-8">
          <div className="lg:hidden flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-400">
              <Activity className="h-5 w-5" />
            </div>
            <div>
              <p className="text-base font-bold tracking-wider uppercase">Tradology</p>
              <p className="text-[11px] text-muted-foreground font-mono">Trading Dashboard</p>
            </div>
          </div>

          <div className="rounded-2xl border border-border/80 bg-card/70 p-8 shadow-2xl shadow-black/20 backdrop-blur-md">
            <div className="space-y-2 text-center mb-8">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-secondary/60 border border-border/60">
                <Lock className="h-5 w-5 text-emerald-400" />
              </div>
              <h2 className="text-xl font-semibold text-foreground">Sign in to continue</h2>
              <p className="text-sm text-muted-foreground">
                Use your authorized Google account to access the trading dashboard.
              </p>
            </div>

            {error && (
              <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                {error === "AccessDenied"
                  ? "Access denied. Your Google account is not on the allowlist."
                  : "Authentication failed. Please try again."}
              </div>
            )}

            <GoogleSignInButton callbackUrl={callbackUrl} />

            <p className="mt-6 text-[11px] text-center text-muted-foreground leading-relaxed">
              Server-side API keys are never exposed to the browser. All backend requests
              are proxied through Next.js with encrypted session protection.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-background text-sm text-muted-foreground">
          Loading...
        </div>
      }
    >
      <LoginContent />
    </Suspense>
  );
}
