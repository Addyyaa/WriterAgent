import type { HTMLAttributes } from "react";

import { cn } from "@/shared/lib/cn";

const toneMap: Record<string, string> = {
  success: "bg-emerald-100 text-emerald-700",
  warning: "bg-amber-100 text-amber-700",
  danger: "bg-rose-100 text-rose-700",
  info: "bg-sky-100 text-sky-700",
  neutral: "bg-slate-100 text-slate-700"
};

export function Badge({ className, children, ...props }: HTMLAttributes<HTMLSpanElement>) {
  const tone = String((props as { "data-tone"?: string })["data-tone"] || "neutral").toLowerCase();
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold",
        toneMap[tone] || toneMap.neutral,
        className
      )}
      {...props}
    >
      {children}
    </span>
  );
}
