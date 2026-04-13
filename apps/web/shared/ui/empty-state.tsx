import type { ReactNode } from "react";

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-ink/20 bg-white/60 p-8 text-center">
      <h3 className="text-lg font-semibold text-graphite">{title}</h3>
      <p className="mt-2 text-sm text-graphite/70">{description}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}
