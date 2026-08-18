import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
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
import { cuToUsd, fmtCU, zeroFillDaily } from "@/lib/format";

function fmtMs(ms?: number): string {
  if (ms == null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

function fmtPeriodDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function Usage() {
  const { client } = useConnection();
  const navigate = useNavigate();
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [daily, setDaily] = useState<DailyUsage | null>(null);
  const [latency, setLatency] = useState<Record<string, LatencyStat> | null>(null);
  const [cuUsdRate, setCuUsdRate] = useState<number | null>(null);
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
    client
      .getConfig()
      .then((c) => setCuUsdRate(typeof c.cu_to_usd.value === "number" ? c.cu_to_usd.value : null))
      .catch(() => null);
  }, [client]);

  const models = usage ? Object.values(usage.by_model) : [];
  const chartData = (daily
    ? zeroFillDaily(daily.daily, 14, {
        requests: 0,
        input_tokens: 0,
        output_tokens: 0,
        compute_units: 0,
      })
    : []
  ).map((d) => ({
    date: d.date.slice(5), // MM-DD
    requests: d.requests,
    cu: d.compute_units,
  }));
  const totalUsd = usage ? cuToUsd(usage.total_compute_units, cuUsdRate) : null;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="display text-4xl">Usage</h1>
        <p className="text-sm text-muted-foreground">This account's usage across the window.</p>
        {usage?.period_start && usage.period_end && (
          <p className="mt-1 text-xs text-muted-foreground">
            Billing period {fmtPeriodDay(usage.period_start)} –{" "}
            {fmtPeriodDay(usage.period_end)} (UTC)
          </p>
        )}
      </div>

      {error && <p className="text-sm text-muted-foreground">Could not load usage: {error}</p>}
      {!error && !usage && <p className="text-sm text-muted-foreground">Loading…</p>}

      {usage && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Requests" value={usage.total_requests.toLocaleString()} />
            <Stat
              label="Compute units"
              value={fmtCU(usage.total_compute_units)}
              sub={totalUsd ?? undefined}
            />
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
                    {models.map((m) => {
                      const usd = cuToUsd(m.compute_units, cuUsdRate);
                      return (
                        <tr
                          key={m.model_tag}
                          onClick={() =>
                            navigate(`/traces?model=${encodeURIComponent(m.model_tag)}`)
                          }
                          className="cursor-pointer border-b border-border/50 transition-colors last:border-0 hover:bg-muted/60"
                        >
                          <td className="py-2">
                            <code className="text-xs">{m.model_tag}</code>
                          </td>
                          <td className="py-2 text-right tabular-nums">{m.requests.toLocaleString()}</td>
                          <td className="py-2 text-right tabular-nums">{m.input_tokens.toLocaleString()}</td>
                          <td className="py-2 text-right tabular-nums">{m.output_tokens.toLocaleString()}</td>
                          <td className="py-2 text-right tabular-nums">
                            {fmtCU(m.compute_units)}
                            {usd && <span className="ml-1 text-xs text-muted-foreground">({usd})</span>}
                          </td>
                        </tr>
                      );
                    })}
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

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card>
      <CardContent className="py-4">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="metric mt-1 tabular-nums">{value}</div>
        {sub && <div className="mt-0.5 text-xs tabular-nums text-muted-foreground">{sub}</div>}
      </CardContent>
    </Card>
  );
}
