import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { type Catalog as CatalogT, GatewayError } from "@/lib/api";
import { useConnection } from "@/lib/connection";

export function Catalog() {
  const { client } = useConnection();
  const [catalog, setCatalog] = useState<CatalogT | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!client) return;
    client
      .getCatalog("coding")
      .then(setCatalog)
      .catch((err) => {
        const msg = (err as GatewayError).message;
        setError(msg);
        toast.error(msg);
      });
  }, [client]);

  if (error) {
    return (
      <PageShell>
        <p className="text-sm text-muted-foreground">Could not load the catalog: {error}</p>
      </PageShell>
    );
  }
  if (!catalog) {
    return (
      <PageShell>
        <p className="text-sm text-muted-foreground">Loading…</p>
      </PageShell>
    );
  }

  // routing_ladder is cheapest → most capable.
  const ladder = catalog.routing_ladder.length
    ? catalog.routing_ladder
    : Object.keys(catalog.tiers);

  return (
    <PageShell>
      <div className="flex flex-col gap-2">
        {ladder.map((tierName) => {
          const tier = catalog.tiers[tierName];
          if (!tier) return null;
          const served = Boolean(tier.model);
          return (
            <Card key={tierName}>
              <CardContent className="flex items-center gap-4 py-4">
                <div className="w-24 shrink-0">
                  <div className="text-sm font-medium capitalize">{tierName}</div>
                  {tier.rel_cost != null && (
                    <div className="text-xs text-muted-foreground">cost {tier.rel_cost}/100</div>
                  )}
                </div>
                <div className="flex-1">
                  {served ? (
                    <div className="flex items-center gap-2">
                      <code className="text-sm">{tier.model}</code>
                      {tier.provider && <Badge variant="secondary">{tier.provider}</Badge>}
                      {tier.served_alternate && <Badge variant="muted">alternate</Badge>}
                    </div>
                  ) : (
                    <span className="text-sm text-muted-foreground">
                      {tier.error ?? "no candidate available"}
                    </span>
                  )}
                  {tier.good_for && (
                    <div className="mt-1 text-xs text-muted-foreground">{tier.good_for}</div>
                  )}
                </div>
                {served ? (
                  <Badge variant="success">served</Badge>
                ) : (
                  <Badge variant="muted">dark</Badge>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
    </PageShell>
  );
}

function PageShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="display text-4xl">Catalog</h1>
        <p className="text-sm text-muted-foreground">
          Curated tier ladder (cheapest → most capable), filtered to the models your key can serve.
        </p>
      </div>
      {children}
    </div>
  );
}
