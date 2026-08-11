/**
 * Typed client for a self-hosted MLPal gateway.
 *
 * Talks only to the gateway's own surfaces — management (`/admin/v1/*`),
 * curated catalog (`/v1/catalog`), and account usage (`/v1/usage/*`) — with an
 * admin-scoped API key (the `MLPAL_AUTH_BACKEND=local` model). No Cognito, no
 * managed backend: this is what ships in the OSS box. Types mirror the gateway's
 * Pydantic schemas.
 */

// ── wire types (mirror the gateway schemas) ─────────────────────────────────

export interface ModelPolicy {
  allow: string[];
  deny: string[];
}

export type BudgetUnit = "usd" | "cu";
export type BudgetWindow = "daily" | "weekly" | "monthly" | "lifetime";

export interface BudgetRule {
  id?: string | null;
  unit: BudgetUnit;
  amount: number;
  window: BudgetWindow;
}

export interface ManagedKey {
  id: number;
  name: string;
  description: string | null;
  key_prefix: string;
  permissions: string[];
  rate_limit_tier: string | null;
  is_active: boolean;
  last_used_at: string | null;
  expires_at: string | null;
  created_at: string | null;
  model_policy: ModelPolicy | null;
  budgets: BudgetRule[] | null;
}

/** Returned only at creation — `secret` is shown once. */
export interface ManagedKeyWithSecret extends ManagedKey {
  secret: string;
}

export interface ManagedKeyList {
  items: ManagedKey[];
  total: number;
}

export interface CreateKeyInput {
  name: string;
  description?: string;
  permissions?: string[];
  expires_at?: string | null;
  model_policy?: ModelPolicy | null;
  budgets?: BudgetRule[] | null;
}

export interface CatalogTier {
  model: string | null;
  provider?: string;
  rel_cost?: number | null;
  good_for?: string;
  caps?: string[];
  served_alternate?: boolean;
  error?: string;
  alternates?: Array<{ model: string; available: boolean }>;
}

export interface Catalog {
  profile: string;
  updated: string | null;
  routing_ladder: string[];
  tiers: Record<string, CatalogTier>;
  models: Record<string, unknown>;
  flagships: Record<string, unknown>;
}

export interface ModelUsage {
  model_tag: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  compute_units: number;
}

export interface ModelPrice {
  input_rate: number | null;
  output_rate: number | null;
  rate_unit: string | null;
}

export interface ModelLineage {
  generation?: number;
  tier?: string;
  tier_rank?: number;
}

export interface ModelCardMeta {
  summary?: string;
  benchmarks?: Record<string, unknown> | null;
}

/** A full registry row + pricing + curated card, from /admin/v1/models. */
export interface RouterCandidate {
  model_tag: string;
  provider: string | null;
  reason: string | null;
  served: boolean;
  unserved_reason: string | null;
}

export interface RouterRoute {
  operation: string;
  /** What a request to this tag resolves to RIGHT NOW (null = would 503). */
  resolved_model_tag: string | null;
  provider: string | null;
  reason: string | null;
  served: boolean;
  unserved_reason: string | null;
  candidates: RouterCandidate[];
}

export interface RouterTag {
  tag: string;
  routes: RouterRoute[];
}

export interface AdminModel {
  model_tag: string;
  display_name: string;
  provider: string;
  provider_model_id: string | null;
  description: string | null;
  capabilities: Record<string, unknown>;
  context_length: number | null;
  max_output_tokens: number | null;
  pricing_tier: string | null;
  priority: number;
  is_active: boolean;
  is_deprecated: boolean;
  deprecation_message: string | null;
  is_paused: boolean;
  pause_reason: string | null;
  source: string;
  pricing: ModelPrice | null;
  lineage: ModelLineage | null;
  card: ModelCardMeta | null;
}

export interface UsageSummary {
  period_start: string | null;
  period_end: string | null;
  total_requests: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_compute_units: number;
  quota_limit: number | null;
  quota_remaining: number | null;
  by_model: Record<string, ModelUsage>;
}

/** One per-request trace record from /admin/v1/traces. */
export interface TraceRecord {
  trace_id: string;
  created_at: string | null;
  api_key_id: number;
  api_key_name: string | null;
  model_tag: string;
  provider: string;
  operation: string;
  input_tokens: number;
  output_tokens: number;
  compute_units: number;
  latency_ms: number | null;
  status: string;
  error_code: string | null;
  metadata: Record<string, unknown> | null;
}

export interface TraceList {
  data: TraceRecord[];
  total: number;
  limit: number;
  offset: number;
  window_hours: number;
}

export interface TraceFilters {
  status?: "success" | "error";
  model_tag?: string;
  operation?: string;
  api_key_id?: number;
  hours?: number;
  limit?: number;
  offset?: number;
}

export interface ConfigItem {
  value: unknown;
  changed_via: string;
  note?: string;
}

export interface GatewayConfigView {
  environment: ConfigItem;
  auth_backend: ConfigItem;
  billing_backend: ConfigItem;
  providers_enabled: ConfigItem;
  capture: CaptureStatus & { changed_via: string };
  cu_to_usd: ConfigItem;
  budget_timezone: ConfigItem;
  docs_enabled: ConfigItem;
  config_file: ConfigItem;
}

export interface KeyUsageSummary {
  api_key_id: number;
  period_start: string;
  period_end: string;
  total_requests: number;
  success_requests: number;
  error_requests: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_compute_units: number;
  last_used_at: string | null;
}

/** Provider key status + live health from /admin/v1/providers. */
export interface ProviderHealth {
  healthy: boolean;
  latency_ms: number;
  error: string | null;
}

export interface ProviderStatus {
  provider: string;
  configured: boolean;
  enabled: boolean;
  models_active: number;
  health: ProviderHealth | null;
}

export interface CaptureStatus {
  enabled: boolean;
  source: "runtime" | "env" | "file" | "default";
  max_body_kb: number;
  retention_days: number;
}

export interface TracePayload {
  trace_id: string;
  request: string;
  response: string;
  request_bytes: number;
  response_bytes: number;
  truncated: boolean;
  captured_at: string | null;
}

export interface LatencyStat {
  p50_ms?: number;
  p95_ms?: number;
  ms_per_output_token?: number;
  samples?: number;
  [k: string]: unknown;
}

export interface BudgetRuleBurn {
  unit: string;
  amount: number;
  window: string;
  used_cu: number;
  cap_cu: number;
  pct: number;
  window_resets: string | null;
}

export interface KeyBudgetBurn {
  api_key_id: number;
  name: string;
  rules: BudgetRuleBurn[];
}

export interface DailyUsageBucket {
  date: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  compute_units: number;
}

export interface DailyUsage {
  period_start: string | null;
  period_end: string | null;
  days: number;
  total_compute_units: number;
  daily: DailyUsageBucket[];
}

// ── error type ──────────────────────────────────────────────────────────────

export class GatewayError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "GatewayError";
    this.status = status;
  }
}

// ── client ──────────────────────────────────────────────────────────────────

export interface GatewayConfig {
  baseUrl: string;
  adminKey: string;
}

function extractMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    if (typeof b.detail === "string") return b.detail;
    if (b.error && typeof b.error === "object") {
      const msg = (b.error as Record<string, unknown>).message;
      if (typeof msg === "string") return msg;
    }
    if (typeof b.error === "string") return b.error;
    if (typeof b.message === "string") return b.message;
  }
  if (typeof body === "string" && body) return body;
  return fallback;
}

export class GatewayClient {
  private readonly baseUrl: string;
  private readonly adminKey: string;

  constructor(config: GatewayConfig) {
    this.baseUrl = config.baseUrl.replace(/\/+$/, "");
    this.adminKey = config.adminKey;
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    let resp: Response;
    try {
      resp = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${this.adminKey}`,
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        // An ops console must never render browser-cached state — a stale
        // cached /v1/catalog once showed every tier as dark for an hour.
        cache: "no-store",
      });
    } catch (e) {
      throw new GatewayError(
        `Could not reach the gateway at ${this.baseUrl}. Is it running and CORS-enabled? (${
          e instanceof Error ? e.message : String(e)
        })`,
        0,
      );
    }

    if (resp.status === 204) return undefined as T;

    const text = await resp.text();
    let parsed: unknown = undefined;
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = text;
      }
    }

    if (!resp.ok) {
      throw new GatewayError(extractMessage(parsed, `HTTP ${resp.status}`), resp.status);
    }
    return parsed as T;
  }

  // management ---------------------------------------------------------------

  listKeys(): Promise<ManagedKeyList> {
    return this.request<ManagedKeyList>("GET", "/admin/v1/keys");
  }

  createKey(input: CreateKeyInput): Promise<ManagedKeyWithSecret> {
    return this.request<ManagedKeyWithSecret>("POST", "/admin/v1/keys", input);
  }

  deleteKey(id: number): Promise<void> {
    return this.request<void>("DELETE", `/admin/v1/keys/${id}`);
  }

  getKeyUsage(id: number): Promise<KeyUsageSummary> {
    return this.request<KeyUsageSummary>("GET", `/admin/v1/keys/${id}/usage`);
  }

  getKeyUsageDaily(id: number, days = 14): Promise<DailyUsage> {
    return this.request<DailyUsage>("GET", `/admin/v1/keys/${id}/usage/daily?days=${days}`);
  }

  getConfig(): Promise<GatewayConfigView> {
    return this.request<GatewayConfigView>("GET", "/admin/v1/config");
  }

  // catalog / usage ----------------------------------------------------------

  getCatalog(profile = "coding"): Promise<Catalog> {
    return this.request<Catalog>("GET", `/v1/catalog?profile=${encodeURIComponent(profile)}`);
  }

  /** Full registry (incl. deprecated/paused/local) with pricing + curated card. */
  listModels(): Promise<{ data: AdminModel[]; total: number }> {
    return this.request<{ data: AdminModel[]; total: number }>("GET", "/admin/v1/models");
  }

  /** Router tags (mlpal/*) with their current per-operation resolution. */
  listRouterTags(): Promise<{ data: RouterTag[] }> {
    return this.request<{ data: RouterTag[] }>("GET", "/admin/v1/router");
  }

  /** Provider key status + live health probes (admin). */
  listProviders(): Promise<{ data: ProviderStatus[] }> {
    return this.request<{ data: ProviderStatus[] }>("GET", "/admin/v1/providers");
  }

  getCaptureStatus(): Promise<CaptureStatus> {
    return this.request<CaptureStatus>("GET", "/admin/v1/capture");
  }

  setCapture(enabled: boolean): Promise<{ enabled: boolean; source: string }> {
    return this.request("PUT", "/admin/v1/capture", { enabled });
  }

  getTracePayload(traceId: string): Promise<TracePayload> {
    return this.request<TracePayload>("GET", `/admin/v1/traces/${encodeURIComponent(traceId)}/payload`);
  }

  getLatencyStats(days = 7): Promise<{ data: Record<string, LatencyStat>; days: number }> {
    return this.request("GET", `/admin/v1/stats/latency?days=${days}&min_samples=1`);
  }

  getBudgetBurn(): Promise<{ data: KeyBudgetBurn[] }> {
    return this.request("GET", "/admin/v1/budgets");
  }

  getDailyUsage(days = 14): Promise<DailyUsage> {
    return this.request<DailyUsage>("GET", `/v1/usage/daily?days=${days}`);
  }

  /** Per-request traces from usage logs (admin). */
  listTraces(filters: TraceFilters = {}): Promise<TraceList> {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(filters)) {
      if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
    }
    const qs = params.toString();
    return this.request<TraceList>("GET", `/admin/v1/traces${qs ? `?${qs}` : ""}`);
  }

  getUsageSummary(): Promise<UsageSummary> {
    return this.request<UsageSummary>("GET", "/v1/usage/summary");
  }

  /** Connectivity + admin-scope probe: lists keys, which requires an admin key. */
  async verify(): Promise<void> {
    await this.listKeys();
  }
}
