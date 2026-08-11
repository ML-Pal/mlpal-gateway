import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import { type RouterTag } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useConnection } from "@/lib/connection";

// ── Router tags ──────────────────────────────────────────────────────────────
// The product's headline: pin `mlpal` once and never touch your code again —
// the target upgrades behind the tag. Rendered as its own band, deliberately
// distinct from provider models.

const TAG_BLURB: Record<string, string> = {
  mlpal: "best quality",
  "mlpal-flash": "lowest latency",
  "mlpal-lite": "most cost-effective",
};

export function RouterTags() {
  const { client } = useConnection();
  const [tags, setTags] = useState<RouterTag[] | null>(null);

  useEffect(() => {
    if (!client) return;
    client.listRouterTags().then((r) => setTags(r.data)).catch(() => setTags([]));
  }, [client]);

  if (!tags || tags.length === 0) return null;
  return <RouterTagSection tags={tags} />;
}

function RouterTagSection({ tags }: { tags: RouterTag[] }) {
  return (
    <section className="rounded-xl border border-[var(--accent)]/25 bg-accent/[0.04] p-5">
      <div className="flex items-center gap-2">
        <Sparkles className="size-4 text-[var(--link)]" />
        <h2 className="text-sm font-semibold">Router tags</h2>
      </div>
      <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
        Stable aliases, not models. Send <code className="text-xs">"model": "mlpal"</code> and the
        gateway picks the best model <em>this deployment serves</em> for that operation, falling
        through a curated, provider-spanning candidate list. Targets upgrade behind the tag; your
        code never changes.
      </p>
      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
        {tags.map((t) => (
          <div key={t.tag} className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-baseline justify-between gap-2">
              <code className="text-sm font-semibold">{t.tag}</code>
              <span className="text-xs text-muted-foreground">{TAG_BLURB[t.tag] ?? "routing alias"}</span>
            </div>
            <div className="mt-3 flex flex-col gap-1.5">
              {t.routes.map((r) => {
                const fallbacks = (r.candidates ?? []).filter(
                  (c) => c.model_tag !== r.resolved_model_tag,
                );
                const title = r.served
                  ? `${r.reason ?? ""}${fallbacks.length ? `\nfallbacks: ${fallbacks.map((c) => `${c.model_tag}${c.served ? "" : ` (${c.unserved_reason})`}`).join(" → ")}` : ""}`
                  : `${r.unserved_reason} — tried: ${(r.candidates ?? []).map((c) => `${c.model_tag} (${c.unserved_reason})`).join(", ")}`;
                return (
                  <div key={r.operation} className="flex items-center gap-2 text-xs" title={title}>
                    <span
                      className={cn(
                        "size-1.5 shrink-0 rounded-full",
                        r.served ? "bg-[var(--success)]" : "border border-muted-foreground/50",
                      )}
                    />
                    <span className="w-20 shrink-0 text-muted-foreground">
                      {r.operation.replace(/_/g, " ")}
                    </span>
                    <code className={cn("truncate", r.served ? "text-foreground" : "text-muted-foreground")}>
                      {r.resolved_model_tag ?? "— none served"}
                    </code>
                    {fallbacks.length > 0 && r.served && (
                      <span className="shrink-0 text-[10px] text-muted-foreground">
                        +{fallbacks.length} fallback{fallbacks.length > 1 ? "s" : ""}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
