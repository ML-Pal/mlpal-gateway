import { CircleStop, Play, Terminal } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { type AdminModel, GatewayError } from "@/lib/api";
import { useConnection } from "@/lib/connection";
import { fmtCU } from "@/lib/format";

interface RunResult {
  content: string;
  model: string;
  latency_ms: number;
  compute_units: number;
  trace_id?: string;
}

export function Playground() {
  const { client, connection } = useConnection();
  const [models, setModels] = useState<AdminModel[]>([]);
  const [model, setModel] = useState("mlpal");
  const [system, setSystem] = useState("");
  const [prompt, setPrompt] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!client) return;
    client
      .listModels()
      .then((r) => {
        // Serving truth, not just registry state: a model without a
        // configured backend (serving_backend null) would only error here.
        const served = r.data.filter(
          (m) =>
            m.is_active &&
            !m.is_deprecated &&
            m.serving_backend !== null &&
            (m.capabilities?.operation ?? "chat") === "chat",
        );
        setModels(served);
        // Default to a model that will actually serve on THIS box: meta-models
        // (mlpal/-flash/-lite) may route to an unconfigured provider.
        if (served.length > 0) setModel(served[0].model_tag);
      })
      .catch(() => null);
  }, [client]);

  const options = useMemo(() => {
    const tags = models.map((m) => m.model_tag).sort();
    return ["mlpal", "mlpal-flash", "mlpal-lite", ...tags];
  }, [models]);

  async function run() {
    if (!connection || !prompt.trim()) {
      toast.error("Write a prompt first.");
      return;
    }
    setRunning(true);
    setResult(null);
    const controller = new AbortController();
    abortRef.current = controller;
    const t0 = performance.now();
    try {
      const messages = [
        ...(system.trim() ? [{ role: "system", content: system.trim() }] : []),
        { role: "user", content: prompt },
      ];
      const r = await fetch(`${connection.baseUrl}/v1/chat/completions`, {
        method: "POST",
        signal: controller.signal,
        headers: {
          Authorization: `Bearer ${connection.adminKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ model, messages }),
      });
      const body = await r.json();
      if (!r.ok) {
        throw new GatewayError(
          body?.error?.message ?? body?.detail ?? `HTTP ${r.status}`,
          r.status,
        );
      }
      setResult({
        content: body.content ?? "(empty)",
        model: body.cost?.model_name ?? model,
        latency_ms: body.cost?.latency_ms ?? Math.round(performance.now() - t0),
        compute_units: body.cost?.compute_units ?? 0,
        trace_id: body.metadata?.trace_id,
      });
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        toast.error((err as Error).message || "Request failed.");
      }
    } finally {
      setRunning(false);
      abortRef.current = null;
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="display flex items-center gap-2 text-4xl">
          <Terminal className="size-6" /> Playground
        </h1>
        <p className="text-sm text-muted-foreground">
          Try any served model right here — same routing, pricing, and traces as your app's
          requests.
        </p>
      </div>

      <Card>
        <CardContent className="flex flex-col gap-4 py-5">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="pg-model">Model</Label>
              <select
                id="pg-model"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="h-9 rounded-md border border-input bg-background px-2 font-mono text-sm"
              >
                {options.map((tag) => (
                  <option key={tag} value={tag}>
                    {tag}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="pg-system">System prompt (optional)</Label>
              <Input
                id="pg-system"
                value={system}
                onChange={(e) => setSystem(e.target.value)}
                placeholder="You are concise."
              />
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="pg-prompt">Prompt</Label>
            <textarea
              id="pg-prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") void run();
              }}
              rows={5}
              placeholder="Ask something… (⌘↵ to run)"
              className="rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          <div className="flex items-center gap-2">
            {running ? (
              <Button variant="outline" onClick={() => abortRef.current?.abort()}>
                <CircleStop className="size-4" /> Stop
              </Button>
            ) : (
              <Button variant="accent" onClick={() => void run()} disabled={!prompt.trim()}>
                <Play className="size-4" /> Run
              </Button>
            )}
            <span className="text-xs text-muted-foreground">
              Runs with your connected admin key.
            </span>
          </div>
        </CardContent>
      </Card>

      {running && <p className="text-sm text-muted-foreground">Waiting for the model…</p>}

      {result && (
        <Card>
          <CardContent className="flex flex-col gap-3 py-5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">
                <code className="text-[11px]">{result.model}</code>
              </Badge>
              <Badge variant="outline">{(result.latency_ms / 1000).toFixed(1)}s</Badge>
              <Badge variant="outline">{fmtCU(result.compute_units)} CU</Badge>
              {result.trace_id && (
                <Link
                  to={`/traces?trace=${encodeURIComponent(result.trace_id)}`}
                  className="ml-auto text-xs link-accent"
                >
                  View in Traces →
                </Link>
              )}
            </div>
            <div className="whitespace-pre-wrap rounded-lg bg-muted p-4 text-sm leading-relaxed">
              {result.content}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
