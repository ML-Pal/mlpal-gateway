import { X } from "lucide-react";
import { useEffect, useState } from "react";
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

import { Badge } from "@/components/ui/badge";
import {
  type DailyUsage,
  type KeyBudgetBurn,
  type KeyUsageSummary,
  type ManagedKey,
  type TraceRecord,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { useConnection } from "@/lib/connection";

function fmtCU(cu: number): string {
  if (!cu) return "0";
  if (cu < 0.0001) return cu.toExponential(1);
  return cu.toFixed(4);
}

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function KeyDetail({
  k,
  burn,
  onClose,
}: {
  k: ManagedKey;
  burn: KeyBudgetBurn | undefined;
  onClose: () => void;
}) {
  const { client } = useConnection();
  const [usage, setUsage] = useState<KeyUsageSummary | null>(null);
  const [daily, setDaily] = useState<DailyUsage | null>(null);
  const [traces, setTraces] = useState<TraceRecord[] | null>(null);

  useEffect(() => {
    if (!client) return;
    client.getKeyUsage(k.id).then(setUsage).catch(() => null);
    client.getKeyUsageDaily(k.id, 14).then(setDaily).catch(() => null);
    client
      .listTraces({ api_key_id: k.id, hours: 24 * 7, limit: 8 })
      .then((r) => setTraces(r.data))
      .catch(() => setTraces([]));
  }, [client, k.id]);

  const chartData = (daily?.daily ?? []).map((d) => ({
    date: d.date.slice(5),
    requests: d.requests,
  }));

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={onClose}>
      <div
        className="h-full w-full max-w-xl overflow-auto border-l border-border bg-card shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold">{k.name}</h2>
            <code className="text-xs text-muted-foreground">
              {k.key_prefix.replace(/\.+$/, "")}…
            </code>
          </div>
          <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:bg-muted">
            <X className="size-4" />
          </button>
        </div>

        <div className="flex flex-col gap-5 p-5">
          {/* usage summary — the "per-key stats" */}
          <div className="grid grid-cols-3 gap-3">
            <MiniStat label="Requests (30d)" value={usage ? String(usage.total_requests) : "…"} />
            <MiniStat
              label="Errors"
              value={usage ? String(usage.error_requests) : "…"}
              tone={usage && usage.error_requests > 0 ? "bad" : undefined}
            />
            <MiniStat label="CU (30d)" value={usage ? fmtCU(usage.total_compute_units) : "…"} />
          </div>
          {/* observability row: cache efficiency, tail latency, TTFT */}
          <div className="grid grid-cols-3 gap-3">
            <MiniStat
              label="Cache hit rate"
              value={usage ? `${(usage.cache_hit_rate * 100).toFixed(0)}%` : "…"}
              sub={usage && usage.cache_read_tokens > 0
                ? `${usage.cache_read_tokens.toLocaleString()} tok read`
                : undefined}
            />
            <MiniStat
              label="Latency p50 / p95"
              value={usage
                ? `${usage.latency_p50_ms ?? "—"} / ${usage.latency_p95_ms ?? "—"} ms`
                : "…"}
              small
            />
            <MiniStat
              label="TTFT p50"
              value={usage ? (usage.ttft_p50_ms != null ? `${usage.ttft_p50_ms} ms` : "—") : "…"}
              sub={usage && usage.total_requests > 0
                ? `${Math.round((usage.stream_requests / usage.total_requests) * 100)}% streamed`
                : undefined}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <MiniStat
              label="Tokens in / out"
              value={
                usage
                  ? `${usage.total_input_tokens.toLocaleString()} / ${usage.total_output_tokens.toLocaleString()}`
                  : "…"
              }
              small
            />
            <MiniStat
              label="Last used"
              value={usage?.last_used_at ? timeAgo(usage.last_used_at) : "never"}
              small
            />
          </div>

          {/* daily chart */}
          {chartData.length > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-medium text-muted-foreground">
                Requests per day (14d)
              </div>
              <div className="h-28">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 2, right: 2, bottom: 0, left: -22 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                    <XAxis
                      dataKey="date"
                      tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
                      axisLine={{ stroke: "var(--border)" }}
                      tickLine={false}
                    />
                    <YAxis
                      allowDecimals={false}
                      tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
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
                    <Bar dataKey="requests" fill="var(--accent)" radius={[2, 2, 0, 0]} maxBarSize={28} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* budgets */}
          {burn && burn.rules.length > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-medium text-muted-foreground">Budgets</div>
              <div className="flex flex-col gap-2">
                {burn.rules.map((r, i) => (
                  <div key={i}>
                    <div className="flex justify-between text-xs">
                      <span className="text-muted-foreground">
                        {r.amount} {r.unit}/{r.window}
                        {r.window_resets &&
                          ` · resets ${new Date(r.window_resets).toLocaleDateString()}`}
                      </span>
                      <span className="font-medium tabular-nums">{r.pct.toFixed(0)}%</span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
                      <div
                        className={cn(
                          "h-full rounded-full",
                          r.pct >= 90
                            ? "bg-[var(--destructive)]"
                            : r.pct >= 70
                              ? "bg-[var(--warning)]"
                              : "bg-[var(--accent)]",
                        )}
                        style={{ width: `${Math.min(100, r.pct)}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* permissions + policy */}
          <div className="flex flex-wrap gap-1.5">
            {k.permissions.map((p) => (
              <Badge key={p} variant="secondary">
                {p}
              </Badge>
            ))}
            {k.model_policy && (
              <Badge variant="outline">allow: {(k.model_policy.allow ?? []).join(", ") || "—"}</Badge>
            )}
          </div>

          {/* recent traces from this key */}
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">Recent requests (7d)</span>
              <Link to="/traces" className="text-xs link-accent">
                all traces →
              </Link>
            </div>
            {traces === null ? (
              <p className="text-xs text-muted-foreground">Loading…</p>
            ) : traces.length === 0 ? (
              <p className="text-xs text-muted-foreground">No requests from this key yet.</p>
            ) : (
              <div className="flex flex-col gap-1.5">
                {traces.map((t) => (
                  <div
                    key={`${t.trace_id}-${t.created_at}`}
                    className="flex items-center gap-2.5 text-sm"
                  >
                    <span
                      className={cn(
                        "size-2 shrink-0 rounded-full",
                        t.status === "success" ? "bg-[var(--success)]" : "bg-[var(--destructive)]",
                      )}
                    />
                    <code className="flex-1 truncate text-xs">{t.model_tag}</code>
                    <span className="text-xs tabular-nums text-muted-foreground">
                      {fmtCU(t.compute_units)} CU
                    </span>
                    <span className="w-14 text-right text-xs text-muted-foreground">
                      {timeAgo(t.created_at)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function MiniStat({
  label,
  value,
  tone,
  small,
  sub,
}: {
  label: string;
  value: string;
  tone?: "bad";
  small?: boolean;
  sub?: string;
}) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div
        className={cn(
          small ? "mt-0.5 text-sm font-semibold" : "metric mt-1",
          "tabular-nums",
          tone === "bad" && "text-[var(--destructive)]",
        )}
      >
        {value}
      </div>
      {sub && <div className="mt-0.5 text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
}
