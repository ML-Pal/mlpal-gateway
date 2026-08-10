import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/cn";

export function CodeBlock({ code, className }: { code: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  function copy() {
    void navigator.clipboard?.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }
  return (
    <div className={cn("group relative", className)}>
      <pre className="overflow-auto rounded-lg bg-[#171714] p-4 text-xs leading-relaxed text-[#ececea] dark:bg-black/40">
        {code}
      </pre>
      <button
        onClick={copy}
        className="absolute right-2 top-2 rounded-md bg-white/10 p-1.5 text-white/70 opacity-0 transition-opacity hover:bg-white/20 hover:text-white group-hover:opacity-100"
        aria-label="Copy code"
      >
        {copied ? <Check className="size-3.5 text-[var(--success)]" /> : <Copy className="size-3.5" />}
      </button>
    </div>
  );
}

/** Tabbed curl / Python / JS snippets. */
export function SnippetTabs({ tabs }: { tabs: { label: string; code: string }[] }) {
  const [active, setActive] = useState(0);
  return (
    <div className="flex flex-col gap-2">
      <div className="inline-flex self-start rounded-full bg-secondary p-1">
        {tabs.map((t, i) => (
          <button
            key={t.label}
            onClick={() => setActive(i)}
            className={cn(
              "rounded-full px-3 py-1 text-xs font-medium transition-colors",
              i === active
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <CodeBlock code={tabs[active].code} />
    </div>
  );
}
