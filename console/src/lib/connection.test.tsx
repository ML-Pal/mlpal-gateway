import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { GatewayClient } from "@/lib/api";
import { ConnectionProvider, useConnection } from "@/lib/connection";

afterEach(() => localStorage.clear());

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <ConnectionProvider>{children}</ConnectionProvider>
);

describe("connection store", () => {
  it("starts disconnected with no client", () => {
    const { result } = renderHook(() => useConnection(), { wrapper });
    expect(result.current.connection).toBeNull();
    expect(result.current.client).toBeNull();
  });

  it("connect persists a trimmed base URL and exposes a client", () => {
    const { result } = renderHook(() => useConnection(), { wrapper });
    act(() => result.current.connect({ baseUrl: "http://localhost:8000/", adminKey: "k" }));
    expect(result.current.connection).toEqual({ baseUrl: "http://localhost:8000", adminKey: "k" });
    expect(result.current.client).toBeInstanceOf(GatewayClient);
    expect(localStorage.getItem("mlpal.console.connection")).toContain("http://localhost:8000");
  });

  it("rehydrates a persisted connection on mount", () => {
    localStorage.setItem(
      "mlpal.console.connection",
      JSON.stringify({ baseUrl: "http://gw", adminKey: "k2" }),
    );
    const { result } = renderHook(() => useConnection(), { wrapper });
    expect(result.current.connection?.adminKey).toBe("k2");
  });

  it("disconnect clears state and storage", () => {
    const { result } = renderHook(() => useConnection(), { wrapper });
    act(() => result.current.connect({ baseUrl: "http://gw", adminKey: "k" }));
    act(() => result.current.disconnect());
    expect(result.current.connection).toBeNull();
    expect(localStorage.getItem("mlpal.console.connection")).toBeNull();
  });
});
