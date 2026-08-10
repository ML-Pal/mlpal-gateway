import { ArrowRight, KeyRound, Plug, RefreshCw, ServerOff } from "lucide-react";
import { Link } from "react-router";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { GatewayError, type ProviderStatus } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useConnection } from "@/lib/connection";

// Dots signal STATUS, never brand — a green dot beside "not configured"
// would read as healthy. Provider identity is carried by the name alone.
const META: Record<string, { label: string; envVar: string }> = {
  openai: { label: "OpenAI", envVar: "OPENAI_API_KEY" },
  anthropic: { label: "Anthropic", envVar: "ANTHROPIC_API_KEY" },
  google: { label: "Google", envVar: "GOOGLE_API_KEY" },
  bedrock: { label: "Bedrock", envVar: "MLPAL_ENABLE_BEDROCK (AWS creds)" },
};

function StatusDot({ state }: { state: "healthy" | "down" | "off" }) {
  if (state === "off") {
    // hollow ring: present but inert
    return <span className="size-2.5 rounded-full border-[1.5px] border-muted-foreground/50" />;
  }
  return (
    <span className="relative flex size-2.5">
      {state === "healthy" && (
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--success)] opacity-40" />
      )}
      <span
        className={cn(
          "relative inline-flex size-2.5 rounded-full",
          state === "healthy" ? "bg-[var(--success)]" : "bg-[var(--destructive)]",
        )}
      />
    </span>
  );
}

export function Providers() {
  const { client } = useConnection();
  const [providers, setProviders] = useState<ProviderStatus[] | null>(null);
  const [probing, setProbing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!client) return;
    setProbing(true);
    setError(null);
    try {
      const res = await client.listProviders();
      setProviders(res.data);
    } catch (err) {
      const msg = (err as GatewayError).message;
      toast.error(msg);
      setError(msg);
      setProviders(null);
    } finally {
      setProbing(false);
    }
  }, [client]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="display flex items-center gap-2 text-4xl">
            <Plug className="size-6" /> Providers
          </h1>
          <p className="text-sm text-muted-foreground">
            The keys this gateway runs on — live health, latency, and what each key unlocks.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void load()} disabled={probing}>
          <RefreshCw className={cn("size-4", probing && "animate-spin")} />
          {probing ? "Probing…" : "Re-probe"}
        </Button>
      </div>

      {error ? (
        <div className="rounded-lg bg-[var(--destructive-bg)] px-4 py-3 text-sm text-[var(--destructive)]">
          Could not load provider status: {error}. Check the gateway is up, then{" "}
          <button onClick={() => void load()} className="font-medium underline">
            retry
          </button>
          .
        </div>
      ) : providers === null ? (
        <p className="text-sm text-muted-foreground">Probing providers…</p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {providers.map((p) => (
            <ProviderCard key={p.provider} p={p} />
          ))}
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Adapters activate per key: set the env var in your <code>.env</code> and restart the
        gateway. Only models from configured, healthy providers are listed and routed.
      </p>
    </div>
  );
}

function ProviderCard({ p }: { p: ProviderStatus }) {
  const meta = META[p.provider] ?? { label: p.provider, envVar: "—" };
  const health = p.health;
  const state: "healthy" | "down" | "off" = !p.enabled ? "off" : health?.healthy ? "healthy" : "down";

  return (
    <Card className={cn(state === "off" && "opacity-75")}>
      <CardContent className="flex flex-col gap-4 py-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <StatusDot state={state} />
            <span className="text-base font-semibold">{meta.label}</span>
          </div>
          {state === "healthy" && <Badge variant="success">operational</Badge>}
          {state === "down" && <Badge variant="destructive">unreachable</Badge>}
          {state === "off" && <Badge variant="muted">not configured</Badge>}
        </div>

        {state === "off" ? (
          <div className="flex items-start gap-3 rounded-lg bg-muted px-3.5 py-3 text-sm text-muted-foreground">
            <ServerOff className="mt-0.5 size-4 shrink-0" />
            <div>
              No key supplied — models from this provider are hidden from the catalog and can't be
              routed. Add <code className="text-xs">{meta.envVar}</code> and restart to enable.{" "}
              <Link to={`/models?provider=${p.provider}`} className="link-accent">
                See what it unlocks
              </Link>
            </div>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-4 text-sm">
              <div>
                <div className="text-xs text-muted-foreground">Key</div>
                <div className="mt-0.5 flex items-center gap-1.5 font-medium">
                  <KeyRound className="size-3.5 text-muted-foreground" /> configured
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Probe latency</div>
                <div className="mt-0.5 font-medium tabular-nums">
                  {health ? `${health.latency_ms}ms` : "—"}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Active models</div>
                <div className="mt-0.5 font-medium tabular-nums">{p.models_active}</div>
              </div>
            </div>
            <Link
              to={`/models?provider=${p.provider}`}
              className="inline-flex items-center gap-1 self-start text-xs link-accent"
            >
              View the {p.models_active} {meta.label} models <ArrowRight className="size-3" />
            </Link>
            {state === "down" && health?.error && (
              <div className="rounded-lg bg-[var(--destructive-bg)] px-3.5 py-2.5 text-xs text-[var(--destructive)]">
                {health.error} — requests to this provider will fail until it recovers; the circuit
                breaker will retry automatically.
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
