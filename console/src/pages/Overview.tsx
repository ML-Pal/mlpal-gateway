import { Activity, ArrowRight, KeyRound } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { SnippetTabs } from "@/components/CodeSnippet";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  type DailyUsage,
  type LatencyStat,
  type ProviderStatus,
  type TraceList,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { useConnection } from "@/lib/connection";
import { curlChat, curlMessages, jsSnippet, pythonSnippet } from "@/lib/snippets";

const PROVIDER_LABEL: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google",
  bedrock: "Bedrock",
};

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

function fmtCU(cu: number): string {
  if (!cu) return "0";
  if (cu < 0.0001) return cu.toExponential(1);
  return cu.toFixed(4);
}

export function Overview() {
  const { client, connection } = useConnection();
  const [providers, setProviders] = useState<ProviderStatus[] | null>(null);
  const [traces, setTraces] = useState<TraceList | null>(null);
  const [keyCount, setKeyCount] = useState<number | null>(null);
  const [daily, setDaily] = useState<DailyUsage | null>(null);
  const [latency, setLatency] = useState<Record<string, LatencyStat> | null>(null);

  useEffect(() => {
    if (!client) return;
    client.listProviders().then((r) => setProviders(r.data)).catch(() => setProviders([]));
    client.listTraces({ hours: 24, limit: 50 }).then(setTraces).catch(() => null);
    client.listKeys().then((r) => setKeyCount(r.total)).catch(() => null);
    client.getDailyUsage(14).then(setDaily).catch(() => null);
    client.getLatencyStats(7).then((r) => setLatency(r.data)).catch(() => null);
  }, [client]);

  const baseUrl = connection?.baseUrl ?? "http://localhost:8000";
  const enabled = (providers ?? []).filter((p) => p.enabled);
  const down = enabled.filter((p) => p.health && !p.health.healthy);
  const firstRun = traces !== null && traces.total === 0;

  const stats = useMemo(() => {
    const list = traces?.data ?? [];
    const errors = list.filter((t) => t.status !== "success").length;
    const cu = list.reduce((acc, t) => acc + (t.compute_units || 0), 0);
    return {
      requests: traces?.total ?? 0,
      errorRate: list.length ? (errors / list.length) * 100 : 0,
      cu,
    };
  }, [traces]);

  const chartData = (daily?.daily ?? []).map((d) => ({
    date: d.date.slice(5),
    requests: d.requests,
  }));

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="display text-4xl">Gateway overview</h1>
        <p className="text-sm text-muted-foreground">
          {firstRun
            ? "You're connected. Three steps to your first request."
            : "Your gateway at a glance."}
        </p>
      </div>

      {/* provider health strip */}
      <div className="flex flex-wrap items-center gap-2">
        {providers === null ? (
          <span className="text-sm text-muted-foreground">Probing providers…</span>
        ) : (
          <>
            {(providers ?? []).map((p) => (
              <Link
                key={p.provider}
                to="/providers"
                className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-1.5 text-sm transition-colors hover:border-ring"
              >
                <span
                  className={cn(
                    "size-2 rounded-full",
                    !p.enabled
                      ? "bg-muted-foreground/40"
                      : p.health?.healthy
                        ? "bg-[var(--success)]"
                        : "bg-[var(--destructive)]",
                  )}
                />
                {PROVIDER_LABEL[p.provider] ?? p.provider}
                {p.enabled && (
                  <span className="text-xs text-muted-foreground">{p.models_active} models</span>
                )}
              </Link>
            ))}
          </>
        )}
      </div>

      {down.length > 0 && (
        <div className="rounded-lg bg-[var(--destructive-bg)] px-4 py-3 text-sm text-[var(--destructive)]">
          {down.map((p) => PROVIDER_LABEL[p.provider] ?? p.provider).join(", ")}{" "}
          {down.length === 1 ? "is" : "are"} unreachable — requests routed there will fail until it
          recovers. <Link to="/providers" className="font-medium underline">See details</Link>
        </div>
      )}

      {firstRun ? (
        <FirstRun baseUrl={baseUrl} keyCount={keyCount ?? 0} />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Requests (24h)" value={traces ? String(stats.requests) : "…"} to="/traces" />
            <Stat
              label="Error rate (24h)"
              value={`${stats.errorRate.toFixed(1)}%`}
              to="/traces"
              tone={stats.errorRate > 5 ? "bad" : stats.errorRate > 0 ? "warn" : "good"}
            />
            <Stat label="Compute units (24h)" value={fmtCU(stats.cu)} to="/usage" />
            <Stat label="API keys" value={keyCount != null ? String(keyCount) : "…"} to="/keys" />
          </div>

          {chartData.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Requests per day (14d)</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-40">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -18 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                      <XAxis
                        dataKey="date"
                        tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                        axisLine={{ stroke: "var(--border)" }}
                        tickLine={false}
                      />
                      <YAxis
                        allowDecimals={false}
                        tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <Tooltip
                        cursor={{ fill: "var(--muted)" }}
                        contentStyle={{
                          background: "var(--card)",
                          border: "1px solid var(--border)",
                          borderRadius: 8,
                          fontSize: 12,
                          color: "var(--foreground)",
                        }}
                      />
                      <Bar dataKey="requests" fill="var(--accent)" radius={[3, 3, 0, 0]} maxBarSize={44} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {/* recent requests */}
            <Card>
              <CardHeader className="flex-row items-center justify-between">
                <CardTitle className="text-sm">Recent requests</CardTitle>
                <Link to="/traces" className="text-xs link-accent">
                  all traces <ArrowRight className="inline size-3" />
                </Link>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {(traces?.data ?? []).slice(0, 6).map((t) => (
                  <Link
                    key={`${t.trace_id}-${t.created_at}`}
                    to="/traces"
                    className="flex items-center gap-2.5 rounded-md px-1 py-1 text-sm transition-colors hover:bg-muted"
                  >
                    <span
                      className={cn(
                        "size-2 shrink-0 rounded-full",
                        t.status === "success" ? "bg-[var(--success)]" : "bg-[var(--destructive)]",
                      )}
                    />
                    <code className="flex-1 truncate text-xs">{t.model_tag}</code>
                    <span className="text-xs tabular-nums text-muted-foreground">
                      {t.latency_ms != null ? `${(t.latency_ms / 1000).toFixed(1)}s` : "—"}
                    </span>
                    <span className="w-8 text-right text-xs text-muted-foreground">
                      {timeAgo(t.created_at)}
                    </span>
                  </Link>
                ))}
                {(traces?.data ?? []).length === 0 && (
                  <p className="text-sm text-muted-foreground">No requests yet.</p>
                )}
              </CardContent>
            </Card>

            {/* latency snapshot */}
            <Card>
              <CardHeader className="flex-row items-center justify-between">
                <CardTitle className="text-sm">Latency by model (7d)</CardTitle>
                <Link to="/usage" className="text-xs link-accent">
                  usage <ArrowRight className="inline size-3" />
                </Link>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {latency && Object.keys(latency).length > 0 ? (
                  Object.entries(latency).map(([model, s]) => (
                    <div key={model} className="flex items-center gap-2.5 px-1 py-1 text-sm">
                      <code className="flex-1 truncate text-xs">{model}</code>
                      <span className="text-xs tabular-nums text-muted-foreground">
                        p50 {s.p50_ms != null ? `${(s.p50_ms / 1000).toFixed(1)}s` : "—"}
                      </span>
                      <span className="text-xs tabular-nums text-muted-foreground">
                        p95 {s.p95_ms != null ? `${(s.p95_ms / 1000).toFixed(1)}s` : "—"}
                      </span>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Appears after enough traffic lands.
                  </p>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Call your gateway</CardTitle>
            </CardHeader>
            <CardContent>
              <SnippetTabs
                tabs={[
                  { label: "curl · OpenAI wire", code: curlChat(baseUrl) },
                  { label: "curl · Anthropic wire", code: curlMessages(baseUrl) },
                  { label: "Python", code: pythonSnippet(baseUrl) },
                  { label: "JavaScript", code: jsSnippet(baseUrl) },
                ]}
              />
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function FirstRun({ baseUrl, keyCount }: { baseUrl: string; keyCount: number }) {
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardContent className="flex items-center gap-4 py-4">
          <StepBadge n={1} done={keyCount > 0} />
          <div className="flex-1">
            <div className="font-medium">Mint an inference key</div>
            <div className="text-sm text-muted-foreground">
              {keyCount > 0
                ? `You have ${keyCount} key${keyCount === 1 ? "" : "s"} — use its secret below.`
                : "Create a key with the permissions and budgets you want."}
            </div>
          </div>
          <Link
            to="/keys"
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            <KeyRound className="size-4" /> Keys
          </Link>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center gap-4">
          <StepBadge n={2} done={false} />
          <div>
            <CardTitle className="text-sm">Send your first request</CardTitle>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Paste your key into any of these — both wires reach every configured model.
            </p>
          </div>
        </CardHeader>
        <CardContent>
          <SnippetTabs
            tabs={[
              { label: "curl · OpenAI wire", code: curlChat(baseUrl) },
              { label: "curl · Anthropic wire", code: curlMessages(baseUrl) },
              { label: "Python", code: pythonSnippet(baseUrl) },
              { label: "JavaScript", code: jsSnippet(baseUrl) },
            ]}
          />
        </CardContent>
      </Card>

      <Card>
        <CardContent className="flex items-center gap-4 py-4">
          <StepBadge n={3} done={false} />
          <div className="flex-1">
            <div className="font-medium">Watch it land</div>
            <div className="text-sm text-muted-foreground">
              Every request appears in Traces with status, latency, tokens, and compute units.
            </div>
          </div>
          <Link
            to="/traces"
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm font-medium hover:bg-muted"
          >
            <Activity className="size-4" /> Traces
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}

function StepBadge({ n, done }: { n: number; done: boolean }) {
  return (
    <span
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold",
        done
          ? "bg-[var(--success-bg)] text-[var(--success)]"
          : "bg-secondary text-secondary-foreground",
      )}
    >
      {done ? "✓" : n}
    </span>
  );
}

function Stat({
  label,
  value,
  to,
  tone,
}: {
  label: string;
  value: string;
  to: string;
  tone?: "good" | "warn" | "bad";
}) {
  return (
    <Link to={to}>
      <Card className="transition-colors hover:border-ring">
        <CardContent className="py-4">
          <div className="text-xs text-muted-foreground">{label}</div>
          <div
            className={cn(
              "metric mt-1 tabular-nums",
              tone === "bad" && "text-[var(--destructive)]",
              tone === "warn" && "text-[var(--warning)]",
              tone === "good" && "text-[var(--success)]",
            )}
          >
            {value}
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
