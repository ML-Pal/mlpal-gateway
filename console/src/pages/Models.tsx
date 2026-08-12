import { Boxes, ExternalLink, Rss, Search, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { type AdminModel, type FeedStatus, GatewayError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useConnection } from "@/lib/connection";

// One color system: semantic status only. Provider identity is TEXT — the
// rainbow dots read as status signals they aren't, and clash with the warm
// obsidian palette. "mlpal" rows are router tags, not provider models — they
// render in their own section above the grid, never as a provider.
const PROVIDER_LABEL: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google",
  bedrock: "Bedrock",
};
const providerLabel = (p: string) => PROVIDER_LABEL[p] ?? p;

function fmtTokens(n: number | null): string {
  if (!n) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return `${n}`;
}
function fmtRate(r: number | null): string {
  if (r == null) return "—";
  return `$${r % 1 === 0 ? r.toFixed(0) : r.toFixed(2)}`;
}
function searchUrl(m: AdminModel): string {
  return `https://www.google.com/search?q=${encodeURIComponent(`${m.display_name} ${m.provider} AI model`)}`;
}
const CAPS = ["tools", "vision", "pdf", "audio"] as const;
const activeCaps = (m: AdminModel) => CAPS.filter((c) => m.capabilities?.[c] === true);

function statusOf(m: AdminModel): { label: string; variant: "warning" | "muted" } | null {
  if (m.is_paused) return { label: "paused", variant: "warning" };
  if (m.is_deprecated) return { label: "deprecated", variant: "warning" };
  if (!m.is_active) return { label: "inactive", variant: "muted" };
  return null;
}

function FeedCard() {
  const { client } = useConnection();
  const [feed, setFeed] = useState<FeedStatus | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!client) return;
    client.getFeedStatus().then(setFeed).catch(() => null);
  }, [client]);

  async function toggle() {
    if (!client || !feed || busy) return;
    const next = feed.mode === "hosted" ? "bundled" : "hosted";
    setBusy(true);
    try {
      const res = await client.setFeedMode(next);
      if (next === "hosted") {
        const sync = res.sync;
        if (sync?.result === "applied") {
          toast.success(`Subscribed — catalog synced (${sync.inserted ?? 0} added, ${sync.updated ?? 0} updated, ${sync.retired ?? 0} retired)`);
        } else if (sync?.result === "unchanged") {
          toast.success("Subscribed — catalog already current");
        } else {
          toast.warning(`Subscribed, but the first sync failed${sync?.error ? `: ${sync.error}` : ""} — will retry on the next cycle`);
        }
      } else {
        toast.success("Unsubscribed — catalog stays as shipped");
      }
      setFeed(await client.getFeedStatus());
    } catch (err) {
      toast.error((err as GatewayError).message);
    } finally {
      setBusy(false);
    }
  }

  if (!feed) return null;
  const hosted = feed.mode === "hosted";
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3">
      <div className="flex items-start gap-3">
        <Rss className={cn("mt-0.5 size-4", hosted ? "text-[var(--link)]" : "text-muted-foreground")} />
        <div>
          <div className="text-sm font-medium">
            Catalog feed:{" "}
            {hosted ? "subscribed — kept current by mlpal.ai" : "bundled — frozen at this version"}
          </div>
          <div className="text-xs text-muted-foreground">
            {hosted
              ? feed.last_sync
                ? `Last sync ${new Date(feed.last_sync.at).toLocaleString()} · ${feed.last_sync.result}${feed.last_sync.feed_version ? ` · feed ${feed.last_sync.feed_version}` : ""}`
                : "First sync pending"
              : "Subscribe and this gateway pulls the curated feed daily — new models appear, retired ones are absorbed, no upgrade needed. Sends only an anonymous install id + version."}
          </div>
        </div>
      </div>
      <button
        onClick={toggle}
        disabled={busy}
        className={cn(
          "rounded-full px-4 py-1.5 text-sm font-medium transition-colors",
          hosted
            ? "bg-secondary text-foreground hover:bg-secondary/70"
            : "bg-[var(--link)] text-background hover:opacity-90",
          busy && "opacity-50",
        )}
      >
        {busy ? "Syncing…" : hosted ? "Unsubscribe" : "Subscribe"}
      </button>
    </div>
  );
}

export function Models() {
  const { client } = useConnection();
  const [models, setModels] = useState<AdminModel[] | null>(null);
  const [searchParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [provider, setProvider] = useState<string | null>(searchParams.get("provider"));
  const [hideRetired, setHideRetired] = useState(true);
  const [selected, setSelected] = useState<AdminModel | null>(null);

  useEffect(() => {
    if (!client) return;
    client
      .listModels()
      .then((r) => setModels(r.data))
      .catch((e) => {
        toast.error((e as GatewayError).message);
        setModels([]);
      });
  }, [client]);

  const providers = useMemo(
    () =>
      Array.from(
        new Set((models ?? []).filter((m) => m.provider !== "mlpal").map((m) => m.provider)),
      ).sort(),
    [models],
  );

  const shown = useMemo(() => {
    let list = (models ?? []).filter((m) => m.provider !== "mlpal");
    if (hideRetired) list = list.filter((m) => m.is_active && !m.is_deprecated);
    if (provider) list = list.filter((m) => m.provider === provider);
    if (q.trim()) {
      const needle = q.toLowerCase();
      list = list.filter(
        (m) =>
          m.display_name.toLowerCase().includes(needle) ||
          m.model_tag.toLowerCase().includes(needle) ||
          (m.card?.summary ?? "").toLowerCase().includes(needle),
      );
    }
    // active first, then by provider + priority
    return [...list].sort(
      (a, b) =>
        Number(b.is_active) - Number(a.is_active) ||
        a.provider.localeCompare(b.provider) ||
        (b.priority ?? 0) - (a.priority ?? 0),
    );
  }, [models, q, provider, hideRetired]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="display flex items-center gap-2 text-4xl">
            <Boxes className="size-6" /> Models
          </h1>
          <p className="text-sm text-muted-foreground">
            {models
              ? `${models.filter((m) => m.provider !== "mlpal" && m.is_active && !m.is_deprecated).length} active of ${models.filter((m) => m.provider !== "mlpal").length} in the registry — unhobbled and priced. Click a card for details.`
              : "Loading the registry…"}
          </p>
        </div>
      </div>

      <p className="text-sm text-muted-foreground">
        This is the shelf — every model with cards and pass-through pricing. Deciding{" "}
        <em>which</em> model should handle a request (or just sending{" "}
        <code className="text-xs">"model": "mlpal"</code>)? That lives in{" "}
        <Link to="/catalog" className="link-accent">Routing</Link>.
      </p>

      <FeedCard />

      {/* filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-52">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search models…"
            className="pl-9"
          />
        </div>
        <div className="inline-flex flex-wrap rounded-full bg-secondary p-1">
          <FilterChip active={provider === null} onClick={() => setProvider(null)}>
            All
          </FilterChip>
          {providers.map((p) => (
            <FilterChip key={p} active={provider === p} onClick={() => setProvider(p)}>
              {providerLabel(p)}
            </FilterChip>
          ))}
        </div>
        <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={hideRetired}
            onChange={(e) => setHideRetired(e.target.checked)}
            className="size-4 accent-[var(--accent)]"
          />
          Hide retired
        </label>
      </div>

      {models === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : shown.length === 0 ? (
        <p className="text-sm text-muted-foreground">No models match.</p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {shown.map((m) => (
            <ModelCard key={m.model_tag} m={m} onOpen={() => setSelected(m)} />
          ))}
        </div>
      )}

      {selected && <ModelDetail m={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors",
        active
          ? "bg-card text-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function ModelCard({ m, onOpen }: { m: AdminModel; onOpen: () => void }) {
  const status = statusOf(m);
  const dim = m.is_deprecated || !m.is_active;
  const summary = m.card?.summary ?? m.description ?? "";
  const tier = m.lineage?.tier ?? m.pricing_tier;

  return (
    <button
      onClick={onOpen}
      className={cn(
        "group flex flex-col gap-3 rounded-lg border border-border bg-card p-4 text-left shadow-sm transition-all",
        "hover:-translate-y-0.5 hover:border-ring hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        dim && "opacity-65",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {providerLabel(m.provider)}
            </span>
            {tier && <Badge variant="outline" className="capitalize">{tier}</Badge>}
          </div>
          <h3 className="mt-1.5 truncate text-base font-semibold">{m.display_name}</h3>
          <code className="text-xs text-muted-foreground">{m.model_tag}</code>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {status && <Badge variant={status.variant}>{status.label}</Badge>}
          {m.source === "local" && <Badge variant="secondary">local</Badge>}
        </div>
      </div>

      {summary && <p className="line-clamp-3 text-sm text-muted-foreground">{summary}</p>}

      <div className="mt-auto flex flex-wrap gap-x-4 gap-y-1 border-t border-border pt-3 text-xs text-muted-foreground tabular-nums">
        <span><span className="font-semibold text-foreground">{fmtTokens(m.context_length)}</span> ctx</span>
        <span><span className="font-semibold text-foreground">{fmtTokens(m.max_output_tokens)}</span> out</span>
        {m.pricing && (
          <span>
            <span className="font-semibold text-foreground">
              {fmtRate(m.pricing.input_rate)} · {fmtRate(m.pricing.output_rate)}
            </span>{" "}
            /1M
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {activeCaps(m).map((c) => (
          <span key={c} className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            {c}
          </span>
        ))}
      </div>
    </button>
  );
}

function ModelDetail({ m, onClose }: { m: AdminModel; onClose: () => void }) {
  const benchmarks = m.card?.benchmarks && typeof m.card.benchmarks === "object" ? m.card.benchmarks : null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[85vh] w-full max-w-lg overflow-auto rounded-2xl border border-border bg-card shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="relative h-1.5 bg-accent/60" />
        <div className="p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <span className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
                {providerLabel(m.provider)}
              </span>
              <h2 className="mt-1 text-lg font-semibold">{m.display_name}</h2>
              <code className="text-xs text-muted-foreground">{m.model_tag}</code>
            </div>
            <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:bg-muted">
              <X className="size-4" />
            </button>
          </div>

          <div className="mt-2 flex flex-wrap gap-1.5">
            {statusOf(m) && <Badge variant={statusOf(m)!.variant}>{statusOf(m)!.label}</Badge>}
            {m.source === "local" && <Badge variant="secondary">local</Badge>}
            {(m.lineage?.tier ?? m.pricing_tier) && (
              <Badge variant="outline" className="capitalize">{m.lineage?.tier ?? m.pricing_tier}</Badge>
            )}
          </div>

          {m.card?.summary && (
            <p className="mt-4 flex gap-2 text-sm">
              <Sparkles className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              <span>{m.card.summary}</span>
            </p>
          )}
          {m.description && m.description !== m.card?.summary && (
            <p className="mt-3 text-sm text-muted-foreground">{m.description}</p>
          )}

          <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
            <Row label="Context">{fmtTokens(m.context_length)} tokens</Row>
            <Row label="Max output">{fmtTokens(m.max_output_tokens)} tokens</Row>
            {m.pricing && (
              <>
                <Row label="Input">{fmtRate(m.pricing.input_rate)} / 1M</Row>
                <Row label="Output">{fmtRate(m.pricing.output_rate)} / 1M</Row>
              </>
            )}
            <Row label="Provider model">{m.provider_model_id ?? "—"}</Row>
            <Row label="Source">{m.source}</Row>
          </dl>

          {activeCaps(m).length > 0 && (
            <div className="mt-4">
              <div className="text-xs font-medium text-muted-foreground">Capabilities</div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {activeCaps(m).map((c) => (
                  <Badge key={c} variant="secondary" className="capitalize">{c}</Badge>
                ))}
              </div>
            </div>
          )}

          {benchmarks && (
            <div className="mt-4">
              <div className="text-xs font-medium text-muted-foreground">Benchmarks</div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {Object.entries(benchmarks).map(([k, v]) => (
                  <span key={k} className="rounded-md border border-border px-2 py-0.5 text-xs">
                    <span className="text-muted-foreground">{k}</span>{" "}
                    <span className="font-medium">{String(v)}</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {(m.deprecation_message || m.pause_reason) && (
            <p className="mt-4 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
              {m.pause_reason ?? m.deprecation_message}
            </p>
          )}

          <a
            href={searchUrl(m)}
            target="_blank"
            rel="noreferrer"
            className="mt-5 inline-flex items-center gap-1.5 text-sm link-accent"
          >
            Learn more about {m.display_name}
            <ExternalLink className="size-3.5" />
          </a>
        </div>
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 font-medium">{children}</dd>
    </div>
  );
}
