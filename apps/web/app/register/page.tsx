"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import type { FormEvent } from "react";

import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";

function RegisterPageContent() {
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const usernameExists = error?.includes("username 已存在") ?? false;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ username, email: email || null, password })
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(String(body?.detail || "注册失败"));
      const next = String(searchParams.get("next") || "").trim();
      window.location.href = next || "/projects";
    } catch (err) {
      setError(String((err as Error)?.message || "注册失败"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md items-center px-6">
      <Card className="w-full p-6">
        <h1 className="font-[var(--font-display)] text-2xl font-semibold text-ink">注册 WriterAgent</h1>
        <p className="mt-1 text-sm text-graphite/70">创建账号后会自动登录并进入项目工作台</p>
        <form className="mt-5 space-y-4" onSubmit={submit}>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="username"
            className="w-full rounded-xl border border-ink/20 px-3 py-2"
            required
          />
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="email (optional)"
            className="w-full rounded-xl border border-ink/20 px-3 py-2"
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="password (>= 6)"
            className="w-full rounded-xl border border-ink/20 px-3 py-2"
            minLength={6}
            required
          />
          {error ? <p className="text-sm text-rose-700">{error}</p> : null}
          {usernameExists ? (
            <p className="text-sm text-amber-700">
              该用户名已注册，请直接
              <Link href="/login" className="ml-1 font-semibold text-ocean underline-offset-2 hover:underline">
                去登录
              </Link>
            </p>
          ) : null}
          <Button className="w-full" type="submit" disabled={loading}>
            {loading ? "注册中..." : "注册并登录"}
          </Button>
        </form>
        <p className="mt-4 text-sm text-graphite/70">
          已有账号？
          <Link href="/login" className="ml-1 font-semibold text-ocean underline-offset-2 hover:underline">
            去登录
          </Link>
        </p>
      </Card>
    </main>
  );
}

export default function RegisterPage() {
  return (
    <Suspense fallback={<main className="mx-auto flex min-h-screen w-full max-w-md items-center px-6" />}>
      <RegisterPageContent />
    </Suspense>
  );
}
