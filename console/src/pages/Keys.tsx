import { Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { SnippetTabs } from "@/components/CodeSnippet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  GatewayError,
  type BudgetUnit,
  type BudgetWindow,
  type CreateKeyInput,
  type KeyBudgetBurn,
  type ManagedKey,
  type ManagedKeyWithSecret,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { KeyDetail } from "@/components/KeyDetail";
import { useConnection } from "@/lib/connection";
import { curlChat, jsSnippet, pythonSnippet } from "@/lib/snippets";

function csv(s: string): string[] {
  return s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

const BLANK_FORM = {
  name: "",
  permissions: "messages",
  allow: "*",
  deny: "",
  budgetAmount: "",
  budgetUnit: "usd" as BudgetUnit,
  budgetWindow: "monthly" as BudgetWindow,
};

export function Keys() {
  const { client, connection } = useConnection();
  const baseUrl = connection?.baseUrl ?? "http://localhost:8000";
  const [keys, setKeys] = useState<ManagedKey[] | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(BLANK_FORM);
  const [creating, setCreating] = useState(false);
  const [newSecret, setNewSecret] = useState<ManagedKeyWithSecret | null>(null);
  const [burn, setBurn] = useState<Record<number, KeyBudgetBurn>>({});
  const [selected, setSelected] = useState<ManagedKey | null>(null);

  const load = useCallback(async () => {
    if (!client) return;
    try {
      const res = await client.listKeys();
      setKeys(res.items);
    } catch (err) {
      toast.error((err as GatewayError).message);
      setKeys([]);
    }
    // Budget burn is best-effort decoration; keys render without it.
    client
      .getBudgetBurn()
      .then((r) => setBurn(Object.fromEntries(r.data.map((b) => [b.api_key_id, b]))))
      .catch(() => null);
  }, [client]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!client) return;
    if (!form.name.trim()) {
      toast.error("Give the key a name.");
      return;
    }
    const input: CreateKeyInput = {
      name: form.name.trim(),
      permissions: csv(form.permissions),
      model_policy: { allow: csv(form.allow), deny: csv(form.deny) },
    };
    const amount = parseFloat(form.budgetAmount);
    if (!Number.isNaN(amount) && amount > 0) {
      input.budgets = [{ unit: form.budgetUnit, amount, window: form.budgetWindow }];
    }
    setCreating(true);
    try {
      const created = await client.createKey(input);
      setNewSecret(created);
      setForm(BLANK_FORM);
      setShowForm(false);
      await load();
    } catch (err) {
      toast.error((err as GatewayError).message);
    } finally {
      setCreating(false);
    }
  }

  async function onDelete(key: ManagedKey) {
    if (!client) return;
    if (!window.confirm(`Revoke key "${key.name}" (${key.key_prefix}…)? This cannot be undone.`)) {
      return;
    }
    try {
      await client.deleteKey(key.id);
      toast.success("Key revoked.");
      await load();
    } catch (err) {
      toast.error((err as GatewayError).message);
    }
  }

  function copy(text: string) {
    void navigator.clipboard?.writeText(text);
    toast.success("Copied.");
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="display text-4xl">API keys</h1>
          <p className="text-sm text-muted-foreground">
            Issue keys scoped by model policy and spend budget.
          </p>
        </div>
        <Button variant="accent" onClick={() => setShowForm((v) => !v)}>
          <Plus className="size-4" /> New key
        </Button>
      </div>

      {newSecret && (
        <Card className="border-[var(--success)]">
          <CardHeader>
            <CardTitle className="text-sm">
              Key created — copy the secret now, it won't be shown again
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex items-center gap-2">
              <code className="flex-1 truncate rounded bg-muted px-3 py-2 text-sm">
                {newSecret.secret}
              </code>
              <Button variant="outline" size="sm" onClick={() => copy(newSecret.secret)}>
                <Copy className="size-4" /> Copy
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setNewSecret(null)}>
                Dismiss
              </Button>
            </div>
            <div>
              <div className="mb-2 text-xs font-medium text-muted-foreground">
                Use it right now — key and gateway URL are already filled in:
              </div>
              <SnippetTabs
                tabs={[
                  { label: "curl", code: curlChat(baseUrl, newSecret.secret) },
                  { label: "Python", code: pythonSnippet(baseUrl, newSecret.secret) },
                  { label: "JavaScript", code: jsSnippet(baseUrl, newSecret.secret) },
                ]}
              />
            </div>
          </CardContent>
        </Card>
      )}

      {showForm && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">New key</CardTitle>
          </CardHeader>
          <CardContent>
            <form className="grid grid-cols-2 gap-4" onSubmit={onCreate}>
              <Field label="Name" className="col-span-2">
                <Input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="team-web"
                />
              </Field>
              <Field label="Permissions (comma-separated)">
                <Input
                  value={form.permissions}
                  onChange={(e) => setForm({ ...form, permissions: e.target.value })}
                  placeholder="messages, embeddings"
                />
              </Field>
              <Field label="Allow models (globs)">
                <Input
                  value={form.allow}
                  onChange={(e) => setForm({ ...form, allow: e.target.value })}
                  placeholder="claude-*, mlpal*"
                />
              </Field>
              <Field label="Deny models (globs)">
                <Input
                  value={form.deny}
                  onChange={(e) => setForm({ ...form, deny: e.target.value })}
                  placeholder="(optional)"
                />
              </Field>
              <Field label="Budget">
                <div className="flex gap-2">
                  <Input
                    type="number"
                    min="0"
                    step="any"
                    value={form.budgetAmount}
                    onChange={(e) => setForm({ ...form, budgetAmount: e.target.value })}
                    placeholder="amount"
                  />
                  <Select
                    value={form.budgetUnit}
                    onChange={(v) => setForm({ ...form, budgetUnit: v as BudgetUnit })}
                    options={["usd", "cu"]}
                  />
                  <Select
                    value={form.budgetWindow}
                    onChange={(v) => setForm({ ...form, budgetWindow: v as BudgetWindow })}
                    options={["daily", "weekly", "monthly", "lifetime"]}
                  />
                </div>
              </Field>
              <div className="col-span-2 flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => setShowForm(false)}>
                  Cancel
                </Button>
                <Button type="submit" disabled={creating}>
                  {creating ? "Creating…" : "Create key"}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      <KeyList keys={keys} onDelete={onDelete} burn={burn} onOpen={setSelected} />

      {selected && (
        <KeyDetail k={selected} burn={burn[selected.id]} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

function Field({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`flex flex-col gap-1.5 ${className ?? ""}`}>
      <Label>{label}</Label>
      {children}
    </div>
  );
}

function Select({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-9 rounded-md border border-input bg-background px-2 text-sm"
    >
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}

function BurnBar({ rule }: { rule: KeyBudgetBurn["rules"][number] }) {
  const pct = Math.min(100, rule.pct);
  const tone =
    rule.pct >= 90
      ? "bg-[var(--destructive)]"
      : rule.pct >= 70
        ? "bg-[var(--warning)]"
        : "bg-primary";
  return (
    <div className="flex items-center gap-2 text-xs">
      <div className="h-1.5 w-28 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${pct}%` }} />
      </div>
      <span className="tabular-nums text-muted-foreground">
        {rule.pct.toFixed(0)}% of {rule.amount} {rule.unit}/{rule.window}
      </span>
    </div>
  );
}

function KeyList({
  keys,
  onDelete,
  burn,
  onOpen,
}: {
  keys: ManagedKey[] | null;
  onDelete: (k: ManagedKey) => void;
  burn: Record<number, KeyBudgetBurn>;
  onOpen: (k: ManagedKey) => void;
}) {
  if (keys === null) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (keys.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-2 py-12 text-center">
          <KeyRound className="size-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">No keys yet. Create one to start.</p>
        </CardContent>
      </Card>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      {keys.map((k) => (
        <Card
          key={k.id}
          onClick={() => onOpen(k)}
          className="cursor-pointer transition-colors hover:border-ring"
        >
          <CardContent className="flex items-center gap-4 py-4">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="font-medium">{k.name}</span>
                <code className="text-xs text-muted-foreground">{k.key_prefix.replace(/\.+$/, "")}…</code>
                {!k.is_active && <Badge variant="muted">inactive</Badge>}
              </div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {k.permissions.map((p) => (
                  <Badge key={p} variant="secondary">
                    {p}
                  </Badge>
                ))}
                {k.model_policy && (
                  <Badge variant="outline">
                    allow: {(k.model_policy.allow ?? []).join(", ") || "—"}
                  </Badge>
                )}
                {(k.budgets ?? []).map((b, i) => (
                  <Badge key={i} variant="outline">
                    {b.amount} {b.unit}/{b.window}
                  </Badge>
                ))}
              </div>
              {(burn[k.id]?.rules ?? []).length > 0 && (
                <div className="mt-2 flex flex-col gap-1">
                  {(burn[k.id]?.rules ?? []).map((r, i) => (
                    <BurnBar key={i} rule={r} />
                  ))}
                </div>
              )}
              <div className="mt-1.5 text-xs text-muted-foreground">
                created {k.created_at ? new Date(k.created_at).toLocaleDateString() : "—"}
                {" · "}
                {k.last_used_at
                  ? `last used ${new Date(k.last_used_at).toLocaleString()}`
                  : "never used"}
                {k.expires_at && ` · expires ${new Date(k.expires_at).toLocaleDateString()}`}
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={(e) => {
                e.stopPropagation();
                onDelete(k);
              }}
              title="Revoke"
              className="text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="size-4" />
            </Button>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
