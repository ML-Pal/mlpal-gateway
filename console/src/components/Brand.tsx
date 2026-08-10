import { cn } from "@/lib/cn";

/** The MLPal brand row — the triangle mark + lowercase wordmark in the display
 * face, exactly as figma-frontend's header renders it (logo.png + dark:invert). */
export function Brand({ size = "md", subtitle }: { size?: "md" | "lg"; subtitle?: string }) {
  return (
    <div className="flex items-center gap-2.5 select-none">
      <img
        src="/logo.png"
        alt="MLpal"
        className={cn("w-auto dark:invert", size === "lg" ? "h-9" : "h-7")}
      />
      <div className="leading-tight">
        <span
          className={cn(
            "font-display block font-[500] tracking-[-0.02em] text-foreground",
            size === "lg" ? "text-2xl" : "text-xl",
          )}
        >
          mlpal
        </span>
        {subtitle && <span className="block text-xs text-muted-foreground">{subtitle}</span>}
      </div>
    </div>
  );
}
