import type { HTMLAttributes } from "react";

import { cn } from "@/shared/lib/cn";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-ink/10 bg-white/80 backdrop-blur-sm shadow-panel",
        className
      )}
      {...props}
    />
  );
}
