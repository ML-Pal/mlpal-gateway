/**
 * Connection state: where the gateway is and which admin key manages it.
 *
 * Persisted in localStorage so a reload keeps you connected. The admin key is a
 * bearer credential — this is an operator's own browser talking to their own
 * self-hosted gateway, the same trust model as any local admin dashboard.
 */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { GatewayClient } from "@/lib/api";

export interface Connection {
  baseUrl: string;
  adminKey: string;
}

const STORAGE_KEY = "mlpal.console.connection";

function load(): Connection | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Connection>;
    if (parsed.baseUrl && parsed.adminKey) {
      return { baseUrl: parsed.baseUrl, adminKey: parsed.adminKey };
    }
  } catch {
    /* ignore malformed storage */
  }
  return null;
}

interface ConnectionContextValue {
  connection: Connection | null;
  client: GatewayClient | null;
  connect: (c: Connection) => void;
  disconnect: () => void;
}

const ConnectionContext = createContext<ConnectionContextValue | null>(null);

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const [connection, setConnection] = useState<Connection | null>(load);

  const connect = useCallback((c: Connection) => {
    const clean: Connection = { baseUrl: c.baseUrl.replace(/\/+$/, ""), adminKey: c.adminKey };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(clean));
    setConnection(clean);
  }, []);

  const disconnect = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setConnection(null);
  }, []);

  const client = useMemo(
    () => (connection ? new GatewayClient(connection) : null),
    [connection],
  );

  const value = useMemo(
    () => ({ connection, client, connect, disconnect }),
    [connection, client, connect, disconnect],
  );

  return <ConnectionContext.Provider value={value}>{children}</ConnectionContext.Provider>;
}

export function useConnection(): ConnectionContextValue {
  const ctx = useContext(ConnectionContext);
  if (!ctx) throw new Error("useConnection must be used within a ConnectionProvider");
  return ctx;
}
