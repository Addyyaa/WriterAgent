import Link from "next/link";

import { Button } from "@/shared/ui/button";

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col items-start justify-center gap-8 px-6 py-16">
      <p className="text-sm uppercase tracking-[0.3em] text-ocean/70">WriterAgent</p>
      <h1 className="max-w-3xl font-[var(--font-display)] text-5xl font-semibold leading-tight text-ink">
        项目工作台与专业控制台，统一管理写作生产链路
      </h1>
      <p className="max-w-2xl text-lg text-graphite/80">
        从项目资产、运行审核、版本回滚到质量指标与故障排查，前后端能力在一个控制面中闭环。
      </p>
      <div className="flex gap-3">
        <Button asChild>
          <Link href="/projects">进入项目工作台</Link>
        </Button>
        <Button asChild variant="secondary">
          <Link href="/metrics">进入专业控制台</Link>
        </Button>
      </div>
    </main>
  );
}
