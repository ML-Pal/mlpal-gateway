import { Pencil, X } from "lucide-react";
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
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  type BudgetUnit,
  type BudgetWindow,
  type DailyUsage,
  GatewayError,
  type KeyBudgetBurn,
  type KeyUsageSummary,
  type ManagedKey,
  type TraceRecord,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { useConnection } from "@/lib/connection";
import { fmtCU, zeroFillDaily } from "@/lib/format";
import { useEscape } from "@/lib/use-escape";

const TIERS = ["free", "standard", "premium", "enterprise"];

function csv(s: string): string[] {
  return s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

interface EditForm {
  tier: string;
  active: boolean;
  allow: string;
  deny: string;
  budgets: Array<{ amount: string; unit: BudgetUnit; window: BudgetWindow }>;
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
  onUpdated,
}: {
  k: ManagedKey;
  burn: KeyBudgetBurn | undefined;
  onClose: () => void;
  onUpdated?: (k: ManagedKey) => void;
}) {
  const { client } = useConnection();
  const [usage, setUsage] = useState<KeyUsageSummary | null>(null);
  const [usageFailed, setUsageFailed] = useState(false);
  const [daily, setDaily] = useState<DailyUsage | null>(null);
  const [traces, setTraces] = useState<TraceRecord[] | null>(null);
  const [edit, setEdit] = useState<EditForm | null>(null);
  const [saving, setSaving] = useState(false);
  useEscape(onClose);

  useEffect(() => {
    if (!client) return;
    client.getKeyUsage(k.id).then(setUsage).catch(() => setUsageFailed(true));
    client.getKeyUsageDaily(k.id, 14).then(setDaily).catch(() => null);
    client
      .listTraces({ api_key_id: k.id, hours: 24 * 7, limit: 8 })
      .then((r) => setTraces(r.data))
      .catch(() => setTraces([]));
  }, [client, k.id]);

  // A failed usage load must read as failed, not as still loading.
  const pending = usageFailed ? "—" : "…";

  const chartData = (daily
    ? zeroFillDaily(daily.daily, 14, {
        requests: 0,
        input_tokens: 0,
        output_tokens: 0,
        compute_units: 0,
      })
    : []
  ).map((d) => ({
    date: d.date.slice(5),
    requests: d.requests,
  }));

  function startEdit() {
    setEdit({
      tier: TIERS.includes(k.rate_limit_tier ?? "") ? k.rate_limit_tier! : "standard",
      active: k.is_active,
      allow: (k.model_policy?.allow ?? []).join(", "),
      deny: (k.model_policy?.deny ?? []).join(", "),
      budgets:
        (k.budgets ?? []).length > 0
          ? k.budgets!.map((b) => ({ amount: String(b.amount), unit: b.unit, window: b.window }))
          : [{ amount: "", unit: "usd", window: "monthly" }],
    });
  }

  async function save() {
    if (!client || !edit) return;
    const budgets = edit.budgets
      .map((b) => ({ ...b, amount: parseFloat(b.amount) }))
      .filter((b) => !Number.isNaN(b.amount) && b.amount > 0)
      .map((b) => ({ unit: b.unit, amount: b.amount, window: b.window }));
    const allow = csv(edit.allow);
    const deny = csv(edit.deny);
    setSaving(true);
    try {
      const updated = await client.updateKey(k.id, {
        rate_limit_tier: edit.tier,
        is_active: edit.active,
        model_policy: allow.length || deny.length ? { allow, deny } : null,
        budgets: budgets.length > 0 ? budgets : null,
      });
      toast.success("Key updated.");
      setEdit(null);
      onUpdated?.(updated);
    } catch (err) {
      toast.error((err as GatewayError).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
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
          <div className="flex items-center gap-1.5">
            {!edit && (
              <button
                onClick={startEdit}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs font-medium text-muted-foreground hover:bg-muted"
              >
                <Pencil className="size-3" /> Edit
              </button>
            )}
            <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:bg-muted">
              <X className="size-4" />
            </button>
          </div>
        </div>

        <div className="flex flex-col gap-5 p-5">
          {edit && (
            <EditPanel
              edit={edit}
              onChange={setEdit}
              onCancel={() => setEdit(null)}
              onSave={() => void save()}
              saving={saving}
            />
          )}
          {/* usage summary — the "per-key stats" */}
          <div className="grid grid-cols-3 gap-3">
            <MiniStat label="Requests (30d)" value={usage ? String(usage.total_requests) : pending} />
            <MiniStat
              label="Errors"
              value={usage ? String(usage.error_requests) : pending}
              tone={usage && usage.error_requests > 0 ? "bad" : undefined}
            />
            <MiniStat label="CU (30d)" value={usage ? fmtCU(usage.total_compute_units) : pending} />
          </div>
          {/* observability row: cache efficiency, tail latency, TTFT */}
          <div className="grid grid-cols-3 gap-3">
            <MiniStat
              label="Cache hit rate"
              value={usage ? `${(usage.cache_hit_rate * 100).toFixed(0)}%` : pending}
              sub={usage && usage.cache_read_tokens > 0
                ? `${usage.cache_read_tokens.toLocaleString()} tok read`
                : undefined}
            />
            <MiniStat
              label="Latency p95"
              value={usage ? (usage.latency_p95_ms != null ? `${usage.latency_p95_ms} ms` : "—") : pending}
              sub={usage && usage.latency_p50_ms != null ? `p50 ${usage.latency_p50_ms} ms` : undefined}
            />
            <MiniStat
              label="TTFT p50"
              value={usage ? (usage.ttft_p50_ms != null ? `${usage.ttft_p50_ms} ms` : "—") : pending}
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
                  : pending
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
              <Link to={`/traces?key=${k.id}`} className="text-xs link-accent">
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

function EditPanel({
  edit,
  onChange,
  onCancel,
  onSave,
  saving,
}: {
  edit: EditForm;
  onChange: (e: EditForm) => void;
  onCancel: () => void;
  onSave: () => void;
  saving: boolean;
}) {
  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border p-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="flex flex-col gap-1.5">
          <Label>Rate limit tier</Label>
          <select
            value={edit.tier}
            onChange={(e) => onChange({ ...edit, tier: e.target.value })}
            className="h-9 rounded-md border border-input bg-background px-2 text-sm"
          >
            {TIERS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label>Status</Label>
          <label className="flex h-9 cursor-pointer select-none items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={edit.active}
              onChange={(e) => onChange({ ...edit, active: e.target.checked })}
              className="size-4 accent-[var(--accent)]"
            />
            {edit.active ? "active" : "inactive"}
          </label>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label>Allow models (globs)</Label>
          <Input
            value={edit.allow}
            onChange={(e) => onChange({ ...edit, allow: e.target.value })}
            placeholder="claude-*, mlpal*"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label>Deny models (globs)</Label>
          <Input
            value={edit.deny}
            onChange={(e) => onChange({ ...edit, deny: e.target.value })}
            placeholder="(optional)"
          />
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label>Budgets</Label>
        <div className="flex flex-col gap-2">
          {edit.budgets.map((b, i) => (
            <div key={i} className="flex gap-2">
              <Input
                type="number"
                min="0"
                step="any"
                value={b.amount}
                onChange={(e) => {
                  const budgets = [...edit.budgets];
                  budgets[i] = { ...b, amount: e.target.value };
                  onChange({ ...edit, budgets });
                }}
                placeholder="amount"
              />
              <select
                value={b.unit}
                onChange={(e) => {
                  const budgets = [...edit.budgets];
                  budgets[i] = { ...b, unit: e.target.value as BudgetUnit };
                  onChange({ ...edit, budgets });
                }}
                className="h-9 rounded-md border border-input bg-background px-2 text-sm"
              >
                {["usd", "cu"].map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
              <select
                value={b.window}
                onChange={(e) => {
                  const budgets = [...edit.budgets];
                  budgets[i] = { ...b, window: e.target.value as BudgetWindow };
                  onChange({ ...edit, budgets });
                }}
                className="h-9 rounded-md border border-input bg-background px-2 text-sm"
              >
                {["daily", "weekly", "monthly", "lifetime"].map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
              {edit.budgets.length > 1 && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label="Remove budget"
                  onClick={() =>
                    onChange({ ...edit, budgets: edit.budgets.filter((_, j) => j !== i) })
                  }
                >
                  <X className="size-4" />
                </Button>
              )}
            </div>
          ))}
          <button
            type="button"
            className="self-start text-xs link-accent"
            onClick={() =>
              onChange({
                ...edit,
                budgets: [...edit.budgets, { amount: "", unit: "usd", window: "daily" }],
              })
            }
          >
            + add another window
          </button>
        </div>
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="button" variant="accent" onClick={onSave} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
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
