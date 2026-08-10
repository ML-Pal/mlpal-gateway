import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/cn";

// Soft-tinted status pills (MLPal DS §05: Deployed/Training/Failed/Queued).
const badgeVariants = cva(
  "inline-flex items-center rounded-md border border-transparent px-2 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        default: "bg-[var(--info-bg)] text-[var(--info)]",
        secondary: "bg-secondary text-secondary-foreground",
        outline: "border-border text-muted-foreground",
        muted: "bg-muted text-muted-foreground",
        success: "bg-[var(--success-bg)] text-[var(--success)]",
        warning: "bg-[var(--warning-bg)] text-[var(--warning)]",
        info: "bg-[var(--info-bg)] text-[var(--info)]",
        destructive: "bg-[var(--destructive-bg)] text-[var(--destructive)]",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export function Badge({
  className,
  variant,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
