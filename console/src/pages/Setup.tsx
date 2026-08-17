import { useState } from "react";
import { toast } from "sonner";

import { Brand } from "@/components/Brand";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { GatewayClient, GatewayError } from "@/lib/api";
import { useConnection } from "@/lib/connection";

const DEFAULT_BASE_URL = "http://localhost:8000";
// When the entered URL doesn't answer, probe the same host on the ports a
// self-hosted gateway commonly lands on (compose remaps when 8000 is taken).
const COMMON_PORTS = [8000, 8090, 8080, 8888];

async function probeAlternatives(baseUrl: string): Promise<string | null> {
  let host = "localhost";
  try {
    host = new URL(baseUrl).hostname || "localhost";
  } catch {
    /* keep default */
  }
  for (const port of COMMON_PORTS) {
    const candidate = `http://${host}:${port}`;
    if (candidate === baseUrl.replace(/\/+$/, "")) continue;
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 1200);
      const r = await fetch(`${candidate}/health`, { signal: controller.signal });
      clearTimeout(timer);
      if (r.ok) return candidate;
    } catch {
      /* try the next port */
    }
  }
  return null;
}

export function Setup() {
  const { connect } = useConnection();
  const [baseUrl, setBaseUrl] = useState(DEFAULT_BASE_URL);
  const [adminKey, setAdminKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [suggestion, setSuggestion] = useState<string | null>(null);

  async function onConnect(e: React.FormEvent) {
    e.preventDefault();
    if (!baseUrl.trim() || !adminKey.trim()) {
      toast.error("Enter the gateway URL and an admin API key.");
      return;
    }
    setBusy(true);
    setSuggestion(null);
    try {
      // Probe connectivity + admin scope before persisting the connection.
      await new GatewayClient({ baseUrl, adminKey }).verify();
      connect({ baseUrl, adminKey });
      toast.success("Connected.");
    } catch (err) {
      const e = err as GatewayError;
      if (e.status === 401 || e.status === 403) {
        toast.error("That key was rejected — it must be an admin-scoped key.");
      } else if (e.status === 0) {
        // Network-level failure: check whether the gateway lives on another port.
        const found = await probeAlternatives(baseUrl);
        if (found) {
          setSuggestion(found);
          toast.error(`Nothing at ${baseUrl} — but a gateway answered at ${found}.`);
        } else {
          toast.error(e.message || "Could not connect.");
        }
      } else {
        toast.error(e.message || "Could not connect.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 px-4">
      <Brand size="lg" />
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Connect to your gateway</CardTitle>
          <CardDescription>
            Point this console at a running MLPal gateway and authenticate with an admin-scoped API
            key.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-4" onSubmit={onConnect}>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="baseUrl">Gateway URL</Label>
              <Input
                id="baseUrl"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder={DEFAULT_BASE_URL}
                autoComplete="off"
              />
              {suggestion && (
                <button
                  type="button"
                  onClick={() => {
                    setBaseUrl(suggestion);
                    setSuggestion(null);
                  }}
                  className="self-start text-xs link-accent"
                >
                  Found a gateway at {suggestion} — use it
                </button>
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="adminKey">Admin API key</Label>
              <Input
                id="adminKey"
                type="password"
                value={adminKey}
                onChange={(e) => setAdminKey(e.target.value)}
                placeholder="mlpal_sk_…"
                autoComplete="off"
              />
              <p className="text-xs text-muted-foreground">
                Started with docker compose? The bootstrap admin key is printed once at seed time —
                run <code>docker compose logs seed</code> to retrieve it. Lost it? Mint another:{" "}
                <code>docker compose run --rm seed python scripts/bootstrap_admin_key.py --name admin-2 --force</code>
              </p>
            </div>
            <Button type="submit" disabled={busy}>
              {busy ? "Connecting…" : "Connect"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
