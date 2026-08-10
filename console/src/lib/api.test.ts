import { afterEach, describe, expect, it, vi } from "vitest";

import { GatewayClient, GatewayError } from "@/lib/api";

function mockFetch(status: number, body: unknown, init?: { throws?: boolean }) {
  const fn = vi.fn(async (_url: string, _opts?: RequestInit) => {
    if (init?.throws) throw new TypeError("Failed to fetch");
    const text = typeof body === "string" ? body : JSON.stringify(body);
    return new Response(status === 204 ? null : text, {
      status,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const client = () => new GatewayClient({ baseUrl: "http://gw.test/", adminKey: "mlpal_sk_admin" });

afterEach(() => vi.unstubAllGlobals());

describe("GatewayClient", () => {
  it("createKey posts to /admin/v1/keys with the bearer header and JSON body", async () => {
    const fetchMock = mockFetch(201, {
      id: 5,
      name: "team-web",
      key_prefix: "mlpal_sk_ab",
      permissions: ["messages"],
      is_active: true,
      secret: "mlpal_sk_abcdef",
    });

    const key = await client().createKey({
      name: "team-web",
      permissions: ["messages"],
      model_policy: { allow: ["claude-*"], deny: [] },
      budgets: [{ unit: "usd", amount: 100, window: "monthly" }],
    });

    expect(key.secret).toBe("mlpal_sk_abcdef");
    const [url, opts] = fetchMock.mock.calls[0];
    const init = opts!;
    expect(url).toBe("http://gw.test/admin/v1/keys"); // trailing slash on baseUrl trimmed
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer mlpal_sk_admin");
    const sent = JSON.parse(init.body as string);
    expect(sent.name).toBe("team-web");
    expect(sent.budgets[0]).toEqual({ unit: "usd", amount: 100, window: "monthly" });
  });

  it("listKeys returns the parsed list", async () => {
    mockFetch(200, { items: [{ id: 1, name: "a" }], total: 1 });
    const res = await client().listKeys();
    expect(res.total).toBe(1);
    expect(res.items[0].name).toBe("a");
  });

  it("deleteKey tolerates a 204 no-content response", async () => {
    mockFetch(204, null);
    await expect(client().deleteKey(2)).resolves.toBeUndefined();
  });

  it("getCatalog forwards the profile query param", async () => {
    const fetchMock = mockFetch(200, { profile: "coding", routing_ladder: [], tiers: {} });
    await client().getCatalog("coding");
    expect(fetchMock.mock.calls[0][0]).toBe("http://gw.test/v1/catalog?profile=coding");
  });

  it("listTraces builds the query string from filters", async () => {
    const fetchMock = mockFetch(200, {
      data: [{ trace_id: "abc", model_tag: "claude-opus-5", status: "success" }],
      total: 1, limit: 100, offset: 0, window_hours: 24,
    });
    const res = await client().listTraces({ status: "error", hours: 24, limit: 100 });
    expect(res.total).toBe(1);
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/admin/v1/traces?");
    expect(url).toContain("status=error");
    expect(url).toContain("hours=24");
    expect(url).toContain("limit=100");
  });

  it("listTraces with no filters hits the bare path", async () => {
    const fetchMock = mockFetch(200, { data: [], total: 0, limit: 50, offset: 0, window_hours: 24 });
    await client().listTraces();
    expect(fetchMock.mock.calls[0][0]).toBe("http://gw.test/admin/v1/traces");
  });

  it("listModels GETs /admin/v1/models and returns the full registry", async () => {
    const fetchMock = mockFetch(200, {
      data: [{ model_tag: "claude-opus-5", provider: "anthropic", is_active: true }],
      total: 1,
    });
    const res = await client().listModels();
    expect(res.total).toBe(1);
    expect(res.data[0].model_tag).toBe("claude-opus-5");
    expect(fetchMock.mock.calls[0][0]).toBe("http://gw.test/admin/v1/models");
  });

  it("maps an error status to GatewayError with the message from the envelope", async () => {
    mockFetch(403, { detail: "no messages scope" });
    await expect(client().listKeys()).rejects.toMatchObject({
      name: "GatewayError",
      status: 403,
      message: "no messages scope",
    });
  });

  it("extracts an Anthropic-style {error:{message}} envelope", async () => {
    mockFetch(400, { error: { message: "bad shape" } });
    await expect(client().listKeys()).rejects.toMatchObject({ status: 400, message: "bad shape" });
  });

  it("wraps a network failure as GatewayError(status 0)", async () => {
    mockFetch(0, null, { throws: true });
    try {
      await client().listKeys();
      expect.unreachable("listKeys should have thrown");
    } catch (e) {
      const err = e as GatewayError;
      expect(err).toBeInstanceOf(GatewayError);
      expect(err.status).toBe(0);
      expect(err.message).toContain("Could not reach the gateway");
    }
  });
});
