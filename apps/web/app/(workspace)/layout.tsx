import Link from "next/link";
import type { ReactNode } from "react";

export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen">
      <header className="border-b border-ink/10 bg-white/70 backdrop-blur">
        <div className="mx-auto flex w-full max-w-7xl items-center justify-between px-6 py-4">
          <Link href="/projects" className="font-[var(--font-display)] text-lg font-semibold text-ink">
            WriterAgent Workspace
          </Link>
          <nav className="flex items-center gap-5 text-sm text-graphite/80">
            <Link href="/projects">Projects</Link>
            <Link href="/metrics">Ops Console</Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl px-6 py-8">{children}</main>
    </div>
  );
}
