"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Cable, CheckCircle2 } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  useConnectExchangeAccount,
  useSupportedExchanges,
  useTestExchangeConnection,
} from "@/hooks/usePlatform";

export default function ConnectExchangePage() {
  const router = useRouter();
  const { data: supported } = useSupportedExchanges();
  const testConnection = useTestExchangeConnection();
  const connect = useConnectExchangeAccount();

  const [exchange, setExchange] = useState("binance");
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [isTestnet, setIsTestnet] = useState(false);
  const [testPassed, setTestPassed] = useState(false);
  const [testMessage, setTestMessage] = useState<string | null>(null);

  const selected = supported?.exchanges?.find((e: any) => e.code === exchange);
  const needsPassphrase = selected?.requires_passphrase;

  const payload = {
    exchange,
    label: label || `${exchange}-main`,
    api_key: apiKey,
    api_secret: apiSecret,
    passphrase: needsPassphrase ? passphrase : undefined,
    is_testnet: isTestnet,
  };

  const resetTest = () => {
    setTestPassed(false);
    setTestMessage(null);
  };

  const handleTest = async () => {
    resetTest();
    try {
      const result = await testConnection.mutateAsync(payload);
      setTestPassed(true);
      setTestMessage(result.message || "Connection successful");
    } catch (err) {
      setTestPassed(false);
      setTestMessage((err as Error).message);
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!testPassed) {
      setTestMessage("Test the connection before saving credentials.");
      return;
    }
    try {
      const account = await connect.mutateAsync(payload);
      router.push(`/accounts/${account.id}`);
    } catch (err) {
      setTestMessage((err as Error).message);
    }
  };

  return (
    <div className="space-y-6 max-w-2xl">
      <PageHeader
        title="Connect Exchange"
        description="API keys are encrypted at rest and never sent to the browser after submission. Use read-only or trade-only permissions — never enable withdrawals."
        icon={Cable}
      />

      <Card className="bg-card/60 border-border/70">
        <CardContent className="p-6">
          <form onSubmit={handleSave} className="space-y-4">
            <div>
              <label className="text-xs text-muted-foreground block mb-1.5">Exchange</label>
              <select
                value={exchange}
                onChange={(e) => {
                  setExchange(e.target.value);
                  resetTest();
                }}
                className="w-full h-10 rounded-lg bg-background border border-border/70 px-3 text-sm"
              >
                {(supported?.exchanges || []).map((ex: any) => (
                  <option key={ex.code} value={ex.code}>
                    {ex.name} ({ex.status})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-xs text-muted-foreground block mb-1.5">Account Label</label>
              <input
                value={label}
                onChange={(e) => {
                  setLabel(e.target.value);
                  resetTest();
                }}
                placeholder="e.g. Binance Main"
                className="w-full h-10 rounded-lg bg-background border border-border/70 px-3 text-sm"
              />
            </div>

            <div>
              <label className="text-xs text-muted-foreground block mb-1.5">API Key</label>
              <input
                value={apiKey}
                onChange={(e) => {
                  setApiKey(e.target.value);
                  resetTest();
                }}
                required
                className="w-full h-10 rounded-lg bg-background border border-border/70 px-3 text-sm font-mono"
              />
            </div>

            <div>
              <label className="text-xs text-muted-foreground block mb-1.5">API Secret</label>
              <input
                type="password"
                value={apiSecret}
                onChange={(e) => {
                  setApiSecret(e.target.value);
                  resetTest();
                }}
                required
                className="w-full h-10 rounded-lg bg-background border border-border/70 px-3 text-sm font-mono"
              />
            </div>

            {needsPassphrase && (
              <div>
                <label className="text-xs text-muted-foreground block mb-1.5">Passphrase (OKX)</label>
                <input
                  type="password"
                  value={passphrase}
                  onChange={(e) => {
                    setPassphrase(e.target.value);
                    resetTest();
                  }}
                  required
                  className="w-full h-10 rounded-lg bg-background border border-border/70 px-3 text-sm font-mono"
                />
              </div>
            )}

            <label className="flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={isTestnet}
                onChange={(e) => {
                  setIsTestnet(e.target.checked);
                  resetTest();
                }}
              />
              Testnet / paper account
            </label>

            <div className="flex flex-col sm:flex-row gap-2 pt-2">
              <Button
                type="button"
                variant="outline"
                disabled={testConnection.isPending || !apiKey || !apiSecret}
                onClick={handleTest}
                className="flex-1"
              >
                {testConnection.isPending ? "Testing..." : "Test Connection"}
              </Button>
              <Button type="submit" disabled={connect.isPending || !testPassed} className="flex-1">
                {connect.isPending ? "Saving & Syncing..." : "Save Account"}
              </Button>
            </div>

            {testPassed && testMessage && (
              <p className="text-xs text-emerald-400 text-center flex items-center justify-center gap-1.5">
                <CheckCircle2 className="h-3.5 w-3.5" />
                {testMessage}
              </p>
            )}
            {!testPassed && testMessage && (
              <p className="text-xs text-rose-400 text-center">{testMessage}</p>
            )}
          </form>
        </CardContent>
      </Card>

      <div className="flex flex-wrap gap-2">
        <Badge variant="outline" className="text-[10px]">
          No withdrawal permissions
        </Badge>
        <Badge variant="outline" className="text-[10px]">
          Encrypted at rest
        </Badge>
        <Badge variant="outline" className="text-[10px]">
          Read-only sync
        </Badge>
      </div>
    </div>
  );
}
