import { Activity, Copy, Download, Pause, Play, ScrollText, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
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
import { fmtCU } from "@/lib/format";
import { curlChat } from "@/lib/snippets";
import { useEscape } from "@/lib/use-escape";

const REFRESH_MS = 5000;
const PAGE_SIZE = 100;
// A search that looks like a trace id (uuid-ish hex) becomes a server-side
// trace_id filter — client-side text match can't find rows beyond this page.
const TRACE_ID_RE = /^[0-9a-f][0-9a-f-]{30,40}$/i;
const WINDOWS = [
  { label: "1h", hours: 1 },
  { label: "24h", hours: 24 },
  { label: "7d", hours: 168 },
  { label: "30d", hours: 720 },
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

export function Traces() {
  const { client, connection } = useConnection();
  const [traces, setTraces] = useState<TraceRecord[] | null>(null);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState<"" | "success" | "error">("");
  const [hours, setHours] = useState<number>(24);
  const [keys, setKeys] = useState<ManagedKey[]>([]);
  const [searchParams, setSearchParams] = useSearchParams();
  const keyParam = searchParams.get("key");
  const parsedKey = keyParam !== null && keyParam !== "" ? Number(keyParam) : NaN;
  const keyId = Number.isFinite(parsedKey) ? parsedKey : null;
  const modelTag = searchParams.get("model");
  const setParam = useCallback(
    (name: string, value: string | null) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value == null) next.delete(name);
          else next.set(name, value);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );
  const setKeyId = useCallback(
    (id: number | null) => setParam("key", id == null ? null : String(id)),
    [setParam],
  );
  const [q, setQ] = useState(() => searchParams.get("trace") ?? "");
  const traceIdQuery = TRACE_ID_RE.test(q.trim()) ? q.trim() : null;
  const [offset, setOffset] = useState(0);
  const [errorTotal, setErrorTotal] = useState<number | null>(null);
  const [windowTotal, setWindowTotal] = useState<number | null>(null);
  const [live, setLive] = useState(true);
  const [selected, setSelected] = useState<TraceRecord | null>(null);
  const [capture, setCapture] = useState<CaptureStatus | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    if (!client) return;
    try {
      const base: TraceFilters = { hours };
      if (keyId != null) base.api_key_id = keyId;
      if (modelTag) base.model_tag = modelTag;
      if (traceIdQuery) base.trace_id = traceIdQuery;
      const page: TraceFilters = { ...base, limit: PAGE_SIZE, offset };
      if (status) page.status = status;
      const [res, errRes, allRes] = await Promise.all([
        client.listTraces(page),
        // True whole-window error count — the loaded page is a sample, not
        // the window, and its error share is not the window's error rate.
        client.listTraces({ ...base, status: "error", limit: 1 }),
        // With a status chip active the page total is status-filtered; the
        // error-rate denominator must be the whole window.
        status ? client.listTraces({ ...base, limit: 1 }) : null,
      ]);
      setTraces(res.data);
      setTotal(res.total);
      setErrorTotal(errRes.total);
      setWindowTotal(allRes ? allRes.total : res.total);
    } catch (err) {
      toast.error((err as GatewayError).message);
      setTraces([]);
      setLive(false);
    }
  }, [client, hours, status, keyId, modelTag, traceIdQuery, offset]);

  // A page offset only makes sense within the filter set it was reached in.
  useEffect(() => {
    setOffset(0);
  }, [hours, status, keyId, modelTag, traceIdQuery]);

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
    if (!q.trim() || traceIdQuery) return traces; // trace-id search is server-side
    const needle = q.toLowerCase();
    return traces.filter(
      (t) =>
        t.trace_id.toLowerCase().includes(needle) ||
        t.model_tag.toLowerCase().includes(needle) ||
        t.operation.toLowerCase().includes(needle),
    );
  }, [traces, q, traceIdQuery]);

  const stats = useMemo(() => {
    const list = traces ?? [];
    const latencies = list.map((t) => t.latency_ms ?? 0).filter((v) => v > 0);
    const cu = list.reduce((acc, t) => acc + (t.compute_units || 0), 0);
    return {
      requests: total,
      errorRate:
        errorTotal != null && windowTotal ? (errorTotal / windowTotal) * 100 : 0,
      avgMs: latencies.length ? latencies.reduce((a, b) => a + b, 0) / latencies.length : 0,
      cu,
    };
  }, [traces, total, errorTotal, windowTotal]);

  const maxLatency = useMemo(
    () => Math.max(1, ...(traces ?? []).map((t) => t.latency_ms ?? 0)),
    [traces],
  );

  const hasFilters = q.trim() !== "" || keyId != null || status !== "" || modelTag != null;

  function clearFilters() {
    setQ("");
    setStatus("");
    setOffset(0);
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const name of ["key", "model", "trace"]) next.delete(name);
        return next;
      },
      { replace: true },
    );
  }

  function exportCsv() {
    const header = [
      "trace_id", "created_at", "model", "provider", "status",
      "latency_ms", "input_tokens", "output_tokens", "compute_units",
    ];
    const lines = [header.join(",")];
    for (const t of traces ?? []) {
      lines.push(
        [
          t.trace_id, t.created_at ?? "", t.model_tag, t.provider, t.status,
          t.latency_ms ?? "", t.input_tokens, t.output_tokens, t.compute_units,
        ].join(","),
      );
    }
    const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `traces-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

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
        <Stat label="Compute units (loaded rows)" value={fmtCU(stats.cu)} />
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
        {modelTag && (
          <button
            onClick={() => setParam("model", null)}
            title="Clear model filter"
            className="inline-flex items-center gap-1.5 rounded-full bg-secondary px-3 py-1 text-xs font-medium"
          >
            model: <code>{modelTag}</code> <X className="size-3" />
          </button>
        )}
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
        !hasFilters && total === 0 ? (
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
            <CardContent className="flex flex-col items-center gap-2 py-8 text-center">
              <p className="text-sm text-muted-foreground">No requests match these filters.</p>
              <button onClick={clearFilters} className="text-xs link-accent">
                Clear filters
              </button>
            </CardContent>
          </Card>
        )
      ) : (
        <Card>
          <CardContent className="p-0">
            <div className="flex items-center justify-end border-b border-border px-4 py-2">
              <button
                onClick={exportCsv}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                <Download className="size-3.5" /> Export CSV
              </button>
            </div>
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
                    tabIndex={0}
                    role="button"
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setSelected(t);
                      }
                    }}
                    className="cursor-pointer border-b border-border/50 transition-colors last:border-0 hover:bg-muted/60 focus-visible:outline-none focus-visible:bg-muted/60"
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
            <div className="flex items-center justify-between border-t border-border px-4 py-2 text-xs text-muted-foreground">
              <span className="tabular-nums">
                Showing {total === 0 ? 0 : offset + 1}–{offset + (traces?.length ?? 0)} of {total}
              </span>
              <div className="flex gap-1.5">
                <button
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  className="rounded-md border border-border px-2.5 py-1 font-medium transition-colors disabled:opacity-40 enabled:hover:bg-muted"
                >
                  Prev
                </button>
                <button
                  disabled={offset + PAGE_SIZE >= total}
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                  className="rounded-md border border-border px-2.5 py-1 font-medium transition-colors disabled:opacity-40 enabled:hover:bg-muted"
                >
                  Next
                </button>
              </div>
            </div>
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
  useEscape(onClose);

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
        role="dialog"
        aria-modal="true"
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
            <Field label="Provider">
              {t.provider}
              {(() => {
                const b = t.metadata?.serving_backend as string | undefined;
                return b && b !== "first_party" ? (
                  <span className="ml-1.5 text-xs text-muted-foreground">via {b}</span>
                ) : null;
              })()}
            </Field>
            <Field label="Operation">{t.operation}</Field>
            <Field label="When">{t.created_at ? new Date(t.created_at).toLocaleString() : "—"}</Field>
            <Field label="Latency">{fmtMs(t.latency_ms)}</Field>
            <Field label="API key">
              <Link to={`/keys?open=${t.api_key_id}`} className="link-accent">
                {t.api_key_name ?? `#${t.api_key_id}`}
              </Link>
            </Field>
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
