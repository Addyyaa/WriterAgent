"use client";

import Link from "next/link";
import { useState } from "react";
import type { FormEvent } from "react";

import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ username, password })
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(String(body?.detail || "登录失败"));
      window.location.href = "/projects";
    } catch (err) {
      setError(String((err as Error)?.message || "登录失败"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md items-center px-6">
      <Card className="w-full p-6">
        <h1 className="font-[var(--font-display)] text-2xl font-semibold text-ink">登录 WriterAgent</h1>
        <p className="mt-1 text-sm text-graphite/70">使用后端账号获取 BFF 会话</p>
        <form className="mt-5 space-y-4" onSubmit={submit}>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="username"
            className="w-full rounded-xl border border-ink/20 px-3 py-2"
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="password"
            className="w-full rounded-xl border border-ink/20 px-3 py-2"
          />
          {error ? <p className="text-sm text-rose-700">{error}</p> : null}
          <Button className="w-full" type="submit" disabled={loading}>
            {loading ? "登录中..." : "登录"}
          </Button>
        </form>
        <p className="mt-4 text-sm text-graphite/70">
          还没有账号？
          <Link href="/register" className="ml-1 font-semibold text-ocean underline-offset-2 hover:underline">
            去注册
          </Link>
        </p>
      </Card>
    </main>
  );
}
