import Link from "next/link";
import type { ReactNode } from "react";

export default function ConsoleLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen">
      <header className="border-b border-ink/10 bg-ocean text-white">
        <div className="mx-auto flex w-full max-w-7xl items-center justify-between px-6 py-4">
          <Link href="/metrics" className="font-[var(--font-display)] text-lg font-semibold">
            WriterAgent Ops Console
          </Link>
          <nav className="flex items-center gap-5 text-sm text-white/90">
            <Link href="/projects">Workspace</Link>
            <Link href="/metrics">Metrics</Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl px-6 py-8">{children}</main>
    </div>
  );
}
