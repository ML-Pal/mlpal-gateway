import { ScrollText, Settings as SettingsIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type ConfigItem, GatewayError, type GatewayConfigView } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useConnection } from "@/lib/connection";

export function Settings() {
  const { client } = useConnection();
  const [config, setConfig] = useState<GatewayConfigView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toggling, setToggling] = useState(false);

  const load = useCallback(async () => {
    if (!client) return;
    setError(null);
    try {
      setConfig(await client.getConfig());
    } catch (err) {
      setError((err as GatewayError).message);
    }
  }, [client]);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggleCapture() {
    if (!client || !config) return;
    setToggling(true);
    try {
      await client.setCapture(!config.capture.enabled);
      await load();
      toast.success(config.capture.enabled ? "Payload capture off." : "Payload capture on.");
    } catch (err) {
      toast.error((err as GatewayError).message);
    } finally {
      setToggling(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="display flex items-center gap-2 text-4xl">
          <SettingsIcon className="size-6" /> Settings
        </h1>
        <p className="text-sm text-muted-foreground">
          What this gateway is running with — and how to change each setting.
        </p>
      </div>

      {error && (
        <div className="rounded-lg bg-[var(--destructive-bg)] px-4 py-3 text-sm text-[var(--destructive)]">
          {error}
        </div>
      )}
      {!error && !config && <p className="text-sm text-muted-foreground">Loading…</p>}

      {config && (
        <>
          {/* Payload capture — the one runtime-changeable setting, promoted */}
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <div>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <ScrollText className="size-4" /> Payload capture
                  <Badge variant="secondary" className="font-normal">runtime</Badge>
                </CardTitle>
                <p className="mt-1 text-sm text-muted-foreground">
                  Store request/response bodies for the Traces debugger. Bodies stay on this box,
                  are size-capped at {config.capture.max_body_kb}KB, and purge after{" "}
                  {config.capture.retention_days} days.
                </p>
              </div>
              <button
                onClick={() => void toggleCapture()}
                disabled={toggling}
                role="switch"
                aria-checked={config.capture.enabled}
                className={cn(
                  "relative h-6 w-11 shrink-0 rounded-full border-0 p-0 transition-colors",
                  config.capture.enabled ? "bg-[var(--success)]" : "bg-muted-foreground/30",
                )}
              >
                {/* left-0 anchors the knob — button default padding otherwise
                    shifts its static position and it overflows the track */}
                <span
                  className={cn(
                    "absolute left-0 top-0.5 size-5 rounded-full bg-white shadow transition-transform",
                    config.capture.enabled ? "translate-x-[22px]" : "translate-x-0.5",
                  )}
                />
              </button>
            </CardHeader>
            <CardContent className="flex items-center gap-2 text-xs text-muted-foreground">
              <Badge variant={config.capture.enabled ? "success" : "muted"}>
                {config.capture.enabled ? "on" : "off"}
              </Badge>
              set via <code>{config.capture.source}</code> · precedence:{" "}
              {config.capture.changed_via}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Gateway configuration</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                Payload capture is the only setting changeable live from here. Everything below is
                deployment configuration — set via env var or <code>config/gateway.yaml</code> and
                applied on restart, on purpose: changing billing backends or provider keys under a
                running gateway isn't something you want a web toggle for.
              </p>
            </CardHeader>
            <CardContent>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="pb-2 font-medium">Setting</th>
                    <th className="pb-2 font-medium">Current value</th>
                    <th className="pb-2 font-medium">Change via</th>
                  </tr>
                </thead>
                <tbody>
                  <Row name="Environment" item={config.environment} />
                  <Row name="Auth backend" item={config.auth_backend} />
                  <Row name="Billing backend" item={config.billing_backend} />
                  <Row name="Providers enabled" item={config.providers_enabled} />
                  <Row name="CU → USD" item={config.cu_to_usd} />
                  <Row name="Budget timezone" item={config.budget_timezone} />
                  <Row name="API docs (/docs)" item={config.docs_enabled} />
                  <Row name="Config file" item={config.config_file} />
                </tbody>
              </table>
            </CardContent>
          </Card>

          <p className="text-xs text-muted-foreground">
            Env-var changes need a gateway restart (<code>docker compose up -d gateway</code>).
            File defaults live in <code>config/gateway.yaml</code>.
          </p>
        </>
      )}
    </div>
  );
}

function Row({ name, item }: { name: string; item: ConfigItem }) {
  const value = Array.isArray(item.value)
    ? (item.value as unknown[]).join(", ") || "none"
    : String(item.value);
  return (
    <tr className="border-b border-border/50 align-top last:border-0">
      <td className="py-2.5 pr-4 font-medium">{name}</td>
      <td className="py-2.5 pr-4">
        <code className="text-xs">{value}</code>
        {item.note && <div className="mt-0.5 text-xs text-muted-foreground">{item.note}</div>}
      </td>
      <td className="py-2.5">
        <code className="text-[11px] text-muted-foreground">{item.changed_via}</code>
        <Badge variant="muted" className="ml-2 align-middle text-[10px] font-normal">
          restart
        </Badge>
      </td>
    </tr>
  );
}
