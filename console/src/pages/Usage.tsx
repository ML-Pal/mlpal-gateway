import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { toast } from "sonner";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  type DailyUsage,
  GatewayError,
  type LatencyStat,
  type UsageSummary,
} from "@/lib/api";
import { useConnection } from "@/lib/connection";

function fmtMs(ms?: number): string {
  if (ms == null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

export function Usage() {
  const { client } = useConnection();
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [daily, setDaily] = useState<DailyUsage | null>(null);
  const [latency, setLatency] = useState<Record<string, LatencyStat> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!client) return;
    client
      .getUsageSummary()
      .then(setUsage)
      .catch((err) => {
        const msg = (err as GatewayError).message;
        setError(msg);
        toast.error(msg);
      });
    client.getDailyUsage(14).then(setDaily).catch(() => null);
    client.getLatencyStats(7).then((r) => setLatency(r.data)).catch(() => null);
  }, [client]);

  const models = usage ? Object.values(usage.by_model) : [];
  const chartData = (daily?.daily ?? []).map((d) => ({
    date: d.date.slice(5), // MM-DD
    requests: d.requests,
    cu: d.compute_units,
  }));

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="display text-4xl">Usage</h1>
        <p className="text-sm text-muted-foreground">This account's usage across the window.</p>
      </div>

      {error && <p className="text-sm text-muted-foreground">Could not load usage: {error}</p>}
      {!error && !usage && <p className="text-sm text-muted-foreground">Loading…</p>}

      {usage && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Requests" value={usage.total_requests.toLocaleString()} />
            <Stat label="Compute units" value={usage.total_compute_units.toFixed(4)} />
            <Stat
              label="Tokens (in / out)"
              value={`${usage.total_input_tokens.toLocaleString()} / ${usage.total_output_tokens.toLocaleString()}`}
            />
          </div>

          {/* daily requests chart */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Requests per day (14d)</CardTitle>
            </CardHeader>
            <CardContent>
              {chartData.length === 0 ? (
                <p className="text-sm text-muted-foreground">No traffic yet.</p>
              ) : (
                <div className="h-48">
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
              )}
            </CardContent>
          </Card>

          {/* latency by model */}
          {latency && Object.keys(latency).length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Observed latency by model (7d)</CardTitle>
              </CardHeader>
              <CardContent>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs text-muted-foreground">
                      <th className="pb-2 font-medium">Model</th>
                      <th className="pb-2 text-right font-medium">p50</th>
                      <th className="pb-2 text-right font-medium">p95</th>
                      <th className="pb-2 text-right font-medium">ms / output token</th>
                      <th className="pb-2 text-right font-medium">Samples</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(latency).map(([model, s]) => (
                      <tr key={model} className="border-b border-border/50 last:border-0">
                        <td className="py-2">
                          <code className="text-xs">{model}</code>
                        </td>
                        <td className="py-2 text-right tabular-nums">{fmtMs(s.p50_ms)}</td>
                        <td className="py-2 text-right tabular-nums">{fmtMs(s.p95_ms)}</td>
                        <td className="py-2 text-right tabular-nums">
                          {s.ms_per_output_token != null ? s.ms_per_output_token.toFixed(1) : "—"}
                        </td>
                        <td className="py-2 text-right tabular-nums">{s.samples ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">By model</CardTitle>
            </CardHeader>
            <CardContent>
              {models.length === 0 ? (
                <p className="text-sm text-muted-foreground">No usage recorded yet.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs text-muted-foreground">
                      <th className="pb-2 font-medium">Model</th>
                      <th className="pb-2 text-right font-medium">Requests</th>
                      <th className="pb-2 text-right font-medium">In</th>
                      <th className="pb-2 text-right font-medium">Out</th>
                      <th className="pb-2 text-right font-medium">CU</th>
                    </tr>
                  </thead>
                  <tbody>
                    {models.map((m) => (
                      <tr key={m.model_tag} className="border-b border-border/50 last:border-0">
                        <td className="py-2">
                          <code className="text-xs">{m.model_tag}</code>
                        </td>
                        <td className="py-2 text-right tabular-nums">{m.requests.toLocaleString()}</td>
                        <td className="py-2 text-right tabular-nums">{m.input_tokens.toLocaleString()}</td>
                        <td className="py-2 text-right tabular-nums">{m.output_tokens.toLocaleString()}</td>
                        <td className="py-2 text-right tabular-nums">{m.compute_units.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardContent className="py-4">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="metric mt-1 tabular-nums">{value}</div>
      </CardContent>
    </Card>
  );
}
