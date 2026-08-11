import { Activity, Copy, Pause, Play, ScrollText, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { CodeBlock } from "@/components/CodeSnippet";
import {
  type CaptureStatus,
  GatewayError,
  type ManagedKey,
  type TraceFilters,
  type TracePayload,
  type TraceRecord,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { useConnection } from "@/lib/connection";
import { curlChat } from "@/lib/snippets";

const REFRESH_MS = 5000;
const WINDOWS = [
  { label: "1h", hours: 1 },
  { label: "24h", hours: 24 },
  { label: "7d", hours: 168 },
] as const;

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function fmtMs(ms: number | null): string {
  if (ms == null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function fmtTok(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return `${n}`;
}

/** CU spans orders of magnitude (a haiku call is ~4e-6) — fixed 4dp collapses
 * small-but-real values to 0.0000, so switch to compact scientific below 1e-4. */
function fmtCU(cu: number): string {
  if (!cu) return "0";
  if (cu < 0.0001) return cu.toExponential(1);
  return cu.toFixed(4);
}

export function Traces() {
  const { client, connection } = useConnection();
  const [traces, setTraces] = useState<TraceRecord[] | null>(null);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState<"" | "success" | "error">("");
  const [hours, setHours] = useState<number>(24);
  const [keys, setKeys] = useState<ManagedKey[]>([]);
  const [searchParams, setSearchParams] = useSearchParams();
  const keyParam = searchParams.get("key");
  const keyId = keyParam !== null && keyParam !== "" ? Number(keyParam) : null;
  const setKeyId = useCallback(
    (id: number | null) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (id == null) next.delete("key");
          else next.set("key", String(id));
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );
  const [q, setQ] = useState("");
  const [live, setLive] = useState(true);
  const [selected, setSelected] = useState<TraceRecord | null>(null);
  const [capture, setCapture] = useState<CaptureStatus | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    if (!client) return;
    try {
      const filters: TraceFilters = { hours, limit: 100 };
      if (status) filters.status = status;
      if (keyId != null) filters.api_key_id = keyId;
      const res = await client.listTraces(filters);
      setTraces(res.data);
      setTotal(res.total);
    } catch (err) {
      toast.error((err as GatewayError).message);
      setTraces([]);
      setLive(false);
    }
  }, [client, hours, status, keyId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!client) return;
    client.getCaptureStatus().then(setCapture).catch(() => null);
    client.listKeys().then((r) => setKeys(r.items)).catch(() => null);
  }, [client]);

  async function toggleCapture() {
    if (!client || !capture) return;
    try {
      await client.setCapture(!capture.enabled);
      const fresh = await client.getCaptureStatus();
      setCapture(fresh);
      toast.success(fresh.enabled ? "Payload capture ON — new requests will store bodies." : "Payload capture off.");
    } catch (err) {
      toast.error((err as GatewayError).message);
    }
  }

  useEffect(() => {
    if (timer.current) clearInterval(timer.current);
    if (live) timer.current = setInterval(() => void load(), REFRESH_MS);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [live, load]);

  const shown = useMemo(() => {
    if (!traces) return [];
    if (!q.trim()) return traces;
    const needle = q.toLowerCase();
    return traces.filter(
      (t) =>
        t.trace_id.toLowerCase().includes(needle) ||
        t.model_tag.toLowerCase().includes(needle) ||
        t.operation.toLowerCase().includes(needle),
    );
  }, [traces, q]);

  const stats = useMemo(() => {
    const list = traces ?? [];
    const errors = list.filter((t) => t.status !== "success").length;
    const latencies = list.map((t) => t.latency_ms ?? 0).filter((v) => v > 0);
    const cu = list.reduce((acc, t) => acc + (t.compute_units || 0), 0);
    return {
      requests: total,
      errorRate: list.length ? (errors / list.length) * 100 : 0,
      avgMs: latencies.length ? latencies.reduce((a, b) => a + b, 0) / latencies.length : 0,
      cu,
    };
  }, [traces, total]);

  const maxLatency = useMemo(
    () => Math.max(1, ...(traces ?? []).map((t) => t.latency_ms ?? 0)),
    [traces],
  );

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="display flex items-center gap-2 text-4xl">
            <Activity className="size-6" /> Traces
          </h1>
          <p className="text-sm text-muted-foreground">
            Every request through the gateway — status, latency, tokens, and compute units.
          </p>
        </div>
        <div className="flex items-center gap-2">
        {capture && (
          <button
            onClick={() => void toggleCapture()}
            title={`Payload capture (${capture.source}) — stores request/response bodies, ${capture.retention_days}d retention`}
            className={cn(
              "inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
              capture.enabled
                ? "border-transparent bg-[var(--warning-bg)] text-[var(--warning)]"
                : "border-border text-muted-foreground hover:bg-muted",
            )}
          >
            <ScrollText className="size-3.5" />
            {capture.enabled ? "Capture on" : "Capture off"}
          </button>
        )}
        <button
          onClick={() => setLive((v) => !v)}
          className={cn(
            "inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
            live
              ? "border-transparent bg-[var(--success-bg)] text-[var(--success)]"
              : "border-border text-muted-foreground hover:bg-muted",
          )}
        >
          {live ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
          {live ? "Live" : "Paused"}
          {live && <span className="relative flex size-2"><span className="absolute inline-flex size-full animate-ping rounded-full bg-[var(--success)] opacity-60" /><span className="relative inline-flex size-2 rounded-full bg-[var(--success)]" /></span>}
        </button>
        </div>
      </div>

      {/* summary strip */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label={`Requests (${hours >= 24 ? `${hours / 24}d` : `${hours}h`})`} value={stats.requests.toLocaleString()} />
        <Stat
          label="Error rate"
          value={`${stats.errorRate.toFixed(1)}%`}
          tone={stats.errorRate > 5 ? "bad" : stats.errorRate > 0 ? "warn" : "good"}
        />
        <Stat label="Avg latency" value={fmtMs(Math.round(stats.avgMs))} />
        <Stat label="Compute units" value={fmtCU(stats.cu)} />
      </div>

      {/* filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Filter by trace id, model, operation…"
          className="max-w-xs font-mono text-xs"
        />
        <div className="inline-flex rounded-full bg-secondary p-1">
          {(["", "success", "error"] as const).map((s) => (
            <Chip key={s || "all"} active={status === s} onClick={() => setStatus(s)}>
              {s === "" ? "All" : s}
            </Chip>
          ))}
        </div>
        {keys.length > 0 && (
          <select
            value={keyId ?? ""}
            onChange={(e) => setKeyId(e.target.value === "" ? null : Number(e.target.value))}
            className={cn(
              "h-8 rounded-md border border-border bg-background px-2.5 text-xs font-medium",
              keyId != null ? "text-foreground" : "text-muted-foreground",
            )}
          >
            <option value="">All keys</option>
            {keys.map((k) => (
              <option key={k.id} value={k.id}>
                {k.name}
              </option>
            ))}
          </select>
        )}
        <div className="ml-auto inline-flex rounded-full bg-secondary p-1">
          {WINDOWS.map((w) => (
            <Chip key={w.label} active={hours === w.hours} onClick={() => setHours(w.hours)}>
              {w.label}
            </Chip>
          ))}
        </div>
      </div>

      {/* request stream */}
      {traces === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : shown.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col gap-4 py-8">
            <div className="text-center text-sm text-muted-foreground">
              No requests in this window yet — run this and watch it appear here live:
            </div>
            <CodeBlock code={curlChat(connection?.baseUrl ?? "http://localhost:8000")} className="mx-auto w-full max-w-2xl" />
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="py-2.5 pl-4 font-medium">Status</th>
                  <th className="py-2.5 font-medium">Time</th>
                  <th className="py-2.5 font-medium">Model</th>
                  <th className="py-2.5 font-medium">Op</th>
                  <th className="py-2.5 text-right font-medium">Tokens in / out</th>
                  <th className="py-2.5 text-right font-medium">CU</th>
                  <th className="py-2.5 pr-4 text-right font-medium">Latency</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((t) => (
                  <tr
                    key={`${t.trace_id}-${t.created_at}`}
                    onClick={() => setSelected(t)}
                    className="cursor-pointer border-b border-border/50 transition-colors last:border-0 hover:bg-muted/60"
                  >
                    <td className="py-2.5 pl-4">
                      <span className="inline-flex items-center gap-2">
                        <span
                          className={cn(
                            "size-2 rounded-full",
                            t.status === "success" ? "bg-[var(--success)]" : "bg-[var(--destructive)]",
                          )}
                        />
                        <span className={cn("text-xs", t.status !== "success" && "text-[var(--destructive)]")}>
                          {t.status === "success" ? "ok" : (t.error_code ?? "error")}
                        </span>
                      </span>
                    </td>
                    <td className="py-2.5 text-xs text-muted-foreground">{timeAgo(t.created_at)}</td>
                    <td className="py-2.5">
                      <code className="text-xs">{t.model_tag}</code>
                      <span className="ml-1.5 text-[10px] text-muted-foreground">{t.provider}</span>
                    </td>
                    <td className="py-2.5 text-xs text-muted-foreground">{t.operation}</td>
                    <td className="py-2.5 text-right text-xs tabular-nums">
                      {fmtTok(t.input_tokens)} / {fmtTok(t.output_tokens)}
                    </td>
                    <td className="py-2.5 text-right text-xs tabular-nums">{fmtCU(t.compute_units)}</td>
                    <td className="py-2.5 pr-4">
                      <div className="flex items-center justify-end gap-2">
                        <div className="h-1 w-16 overflow-hidden rounded-full bg-muted">
                          <div
                            className="h-full rounded-full bg-[var(--accent)]/80"
                            style={{ width: `${Math.min(100, ((t.latency_ms ?? 0) / maxLatency) * 100)}%` }}
                          />
                        </div>
                        <span className="w-12 text-right text-xs tabular-nums">{fmtMs(t.latency_ms)}</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {selected && (
        <TraceDetail
          t={selected}
          captureEnabled={capture?.enabled ?? false}
          onEnableCapture={() => void toggleCapture()}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "good" | "warn" | "bad" }) {
  return (
    <Card>
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
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors",
        active
          ? "bg-card text-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function TraceDetail({
  t,
  captureEnabled,
  onEnableCapture,
  onClose,
}: {
  t: TraceRecord;
  captureEnabled: boolean;
  onEnableCapture: () => void;
  onClose: () => void;
}) {
  const { client, connection } = useConnection();
  const [payload, setPayload] = useState<TracePayload | null | "missing">(null);
  const [tab, setTab] = useState<"request" | "response">("request");

  useEffect(() => {
    if (!client) return;
    client
      .getTracePayload(t.trace_id)
      .then(setPayload)
      .catch(() => setPayload("missing"));
  }, [client, t.trace_id]);

  function copy(text: string) {
    void navigator.clipboard?.writeText(text);
    toast.success("Copied.");
  }

  function pretty(raw: string): string {
    try {
      return JSON.stringify(JSON.parse(raw), null, 2);
    } catch {
      return raw;
    }
  }

  const isV2 = t.metadata?.api === "v2_messages";
  const curl =
    payload && payload !== "missing"
      ? `curl ${connection?.baseUrl ?? ""}${isV2 ? "/v1/messages" : "/v1/chat/completions"} \\
  -H "Authorization: Bearer $MLPAL_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '${pretty(payload.request).replace(/'/g, "'\\''")}'`
      : null;

  const errorDetail = (t.metadata?.error_detail as string | undefined) ?? null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={onClose}>
      <div
        className="h-full w-full max-w-xl overflow-auto border-l border-border bg-card shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "size-2.5 rounded-full",
                t.status === "success" ? "bg-[var(--success)]" : "bg-[var(--destructive)]",
              )}
            />
            <h2 className="text-sm font-semibold">Request trace</h2>
          </div>
          <div className="flex items-center gap-1.5">
            {curl && (
              <button
                onClick={() => copy(curl)}
                className="rounded-md border border-border px-2.5 py-1 text-xs font-medium text-muted-foreground hover:bg-muted"
              >
                Copy as curl
              </button>
            )}
            <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:bg-muted">
              <X className="size-4" />
            </button>
          </div>
        </div>

        <div className="flex flex-col gap-5 p-5">
          <div>
            <div className="text-xs text-muted-foreground">Trace ID</div>
            <div className="mt-1 flex items-center gap-2">
              <code className="flex-1 truncate rounded bg-muted px-2 py-1 text-xs">{t.trace_id}</code>
              <button onClick={() => copy(t.trace_id)} className="rounded-md p-1.5 text-muted-foreground hover:bg-muted">
                <Copy className="size-3.5" />
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
            <Field label="Model"><code className="text-xs">{t.model_tag}</code></Field>
            <Field label="Provider">{t.provider}</Field>
            <Field label="Operation">{t.operation}</Field>
            <Field label="When">{t.created_at ? new Date(t.created_at).toLocaleString() : "—"}</Field>
            <Field label="Latency">{fmtMs(t.latency_ms)}</Field>
            <Field label="API key">{t.api_key_name ?? `#${t.api_key_id}`}</Field>
            <Field label="Input tokens">{t.input_tokens.toLocaleString()}</Field>
            <Field label="Output tokens">{t.output_tokens.toLocaleString()}</Field>
          </div>

          <div className="rounded-lg border border-border p-3.5">
            <div className="text-xs font-medium text-muted-foreground">Compute units</div>
            <div className="metric mt-1.5 tabular-nums">{fmtCU(t.compute_units)}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              Provider pass-through, no markup.
            </div>
          </div>

          {(t.error_code || errorDetail) && (
            <div className="rounded-lg bg-[var(--destructive-bg)] px-3.5 py-2.5 text-xs text-[var(--destructive)]">
              <div className="font-medium">{t.error_code}</div>
              {errorDetail && <div className="mt-1 whitespace-pre-wrap">{errorDetail}</div>}
            </div>
          )}

          {/* Captured payload */}
          <div>
            <div className="mb-2 flex items-center gap-2">
              <span className="text-xs font-medium text-muted-foreground">Payload</span>
              {payload && payload !== "missing" && payload.truncated && (
                <Badge variant="warning">truncated</Badge>
              )}
            </div>
            {payload === null ? (
              <p className="text-xs text-muted-foreground">Loading…</p>
            ) : payload === "missing" ? (
              <div className="rounded-lg bg-muted px-3.5 py-3 text-xs text-muted-foreground">
                No payload captured for this request.
                {!captureEnabled && (
                  <>
                    {" "}
                    <button onClick={onEnableCapture} className="link-accent">
                      Turn capture on
                    </button>{" "}
                    to store request/response bodies for future requests (opt-in; bodies stay on
                    this box and are purged by retention).
                  </>
                )}
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                <div className="inline-flex self-start rounded-full bg-secondary p-1">
                  {(["request", "response"] as const).map((k) => (
                    <button
                      key={k}
                      onClick={() => setTab(k)}
                      className={cn(
                        "rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors",
                        tab === k
                          ? "bg-card text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {k}
                      <span className="ml-1.5 text-[10px] text-muted-foreground">
                        {((k === "request" ? payload.request_bytes : payload.response_bytes) / 1024).toFixed(1)}KB
                      </span>
                    </button>
                  ))}
                </div>
                <pre className="max-h-96 overflow-auto rounded-lg bg-muted p-3 text-[11px] leading-relaxed">
                  {pretty(tab === "request" ? payload.request : payload.response)}
                </pre>
              </div>
            )}
          </div>

          {t.metadata && Object.keys(t.metadata).length > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-medium text-muted-foreground">Metadata</div>
              <pre className="overflow-auto rounded-lg bg-muted p-3 text-[11px] leading-relaxed">
                {JSON.stringify(t.metadata, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 font-medium">{children}</dd>
    </div>
  );
}
