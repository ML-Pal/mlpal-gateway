import {
  Activity,
  BarChart3,
  BookOpen,
  Boxes,
  Home,
  KeyRound,
  LogOut,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Plug,
  Settings as SettingsIcon,
  Terminal,
  Sun,
  Waypoints,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet } from "react-router";

import { Brand } from "@/components/Brand";
import { Button } from "@/components/ui/button";
import { type ProviderStatus } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useConnection } from "@/lib/connection";
import { currentTheme, toggleTheme } from "@/lib/theme";

const NAV = [
  { to: "/overview", label: "Overview", icon: Home },
  { to: "/traces", label: "Traces", icon: Activity },
  { to: "/playground", label: "Playground", icon: Terminal },
  { to: "/providers", label: "Providers", icon: Plug },
  { to: "/keys", label: "Keys", icon: KeyRound },
  { to: "/models", label: "Models", icon: Boxes },
  { to: "/catalog", label: "Routing", icon: Waypoints },
  { to: "/usage", label: "Usage", icon: BarChart3 },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

const PROVIDER_LABEL: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google",
  bedrock: "Bedrock",
};

const SIDEBAR_KEY = "mlpal-console.sidebar";

export function Layout() {
  const { connection, disconnect, client } = useConnection();
  const [theme, setTheme] = useState(currentTheme());
  const [down, setDown] = useState<ProviderStatus[]>([]);
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(SIDEBAR_KEY) === "collapsed",
  );

  function toggleSidebar() {
    setCollapsed((v) => {
      localStorage.setItem(SIDEBAR_KEY, v ? "expanded" : "collapsed");
      return !v;
    });
  }

  // Global provider-health awareness: a down provider should be visible from
  // every page, not just the Providers tab. Light 60s poll.
  useEffect(() => {
    if (!client) return;
    let cancelled = false;
    const check = () =>
      client
        .listProviders()
        .then((r) => {
          if (!cancelled) setDown(r.data.filter((p) => p.enabled && p.health && !p.health.healthy));
        })
        .catch(() => null);
    void check();
    const t = setInterval(check, 60_000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [client]);

  return (
    // h-screen + overflow-hidden pins the shell to the viewport: long page
    // content scrolls inside <main>, never the body — so the sidebar's bottom
    // controls (theme, disconnect, collapse) are always reachable.
    <div className="flex h-screen overflow-hidden">
      <aside
        className={cn(
          "flex shrink-0 flex-col overflow-y-auto border-r border-border bg-card transition-[width] duration-200",
          collapsed ? "w-16" : "w-60",
        )}
      >
        <div className={cn("py-5", collapsed ? "px-0" : "px-5")}>
          {collapsed ? (
            <img src="/logo.png" alt="MLpal" className="mx-auto h-7 w-auto dark:invert" />
          ) : (
            <>
              <Brand subtitle="gateway console" />
              <div
                className="mt-2 truncate text-xs text-muted-foreground"
                title={connection?.baseUrl}
              >
                {connection?.baseUrl}
              </div>
            </>
          )}
        </div>
        <nav className={cn("flex flex-1 flex-col gap-1", collapsed ? "px-2" : "px-3")}>
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              title={collapsed ? label : undefined}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md py-2 text-sm font-medium transition-colors",
                  collapsed ? "justify-center px-0" : "px-3",
                  isActive
                    ? "bg-accent/15 font-semibold text-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )
              }
            >
              <Icon className="size-4 shrink-0" />
              {!collapsed && label}
            </NavLink>
          ))}
        </nav>
        <div className={cn("flex flex-col gap-1 p-3", collapsed && "items-center p-2")}>
          <a
            href={`${connection?.baseUrl ?? ""}/docs`}
            target="_blank"
            rel="noreferrer"
            title={collapsed ? "API reference" : undefined}
            className={cn(
              "flex items-center gap-3 rounded-md py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
              collapsed ? "justify-center px-2" : "px-3",
            )}
          >
            <BookOpen className="size-4" />
            {!collapsed && "API reference"}
          </a>
          <Button
            variant="ghost"
            size="sm"
            title={collapsed ? (theme === "dark" ? "Light mode" : "Dark mode") : undefined}
            className={cn("w-full", collapsed ? "justify-center" : "justify-start")}
            onClick={() => setTheme(toggleTheme())}
          >
            {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
            {!collapsed && (theme === "dark" ? "Light mode" : "Dark mode")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            title={collapsed ? "Disconnect" : undefined}
            className={cn("w-full", collapsed ? "justify-center" : "justify-start")}
            onClick={disconnect}
          >
            <LogOut className="size-4" />
            {!collapsed && "Disconnect"}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className={cn("w-full", collapsed ? "justify-center" : "justify-start")}
            onClick={toggleSidebar}
          >
            {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
            {!collapsed && "Collapse"}
          </Button>
        </div>
      </aside>
      <main className="atmos flex-1 overflow-auto">
        {down.length > 0 && (
          <div className="border-b border-[var(--destructive)]/20 bg-[var(--destructive-bg)] px-8 py-2 text-sm text-[var(--destructive)]">
            {down.map((p) => PROVIDER_LABEL[p.provider] ?? p.provider).join(", ")}{" "}
            {down.length === 1 ? "is" : "are"} unreachable — requests routed there will fail.{" "}
            <Link to="/providers" className="font-medium underline">
              Details
            </Link>
          </div>
        )}
        <div className="page-anim mx-auto max-w-5xl px-8 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
