"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";

type ToastVariant = "success" | "error" | "warning" | "info";

interface ToastItem {
  id: number;
  message: string;
  variant: ToastVariant;
}

let _dispatch: ((item: Omit<ToastItem, "id">) => void) | null = null;
let _nextId = 1;

export const toast = {
  success: (message: string) => _dispatch?.({ message, variant: "success" }),
  error: (message: string) => _dispatch?.({ message, variant: "error" }),
  warning: (message: string) => _dispatch?.({ message, variant: "warning" }),
  info: (message: string) => _dispatch?.({ message, variant: "info" }),
};

const ICON_MAP: Record<ToastVariant, typeof CheckCircle2> = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

const STYLE_MAP: Record<ToastVariant, string> = {
  success: "border-emerald-300 bg-emerald-50 text-emerald-900",
  error: "border-rose-300 bg-rose-50 text-rose-900",
  warning: "border-amber-300 bg-amber-50 text-amber-900",
  info: "border-sky-300 bg-sky-50 text-sky-900",
};

const DURATION_MS = 4000;

export function ToastProvider() {
  const [items, setItems] = useState<ToastItem[]>([]);
  const timersRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const remove = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
  }, []);

  useEffect(() => {
    _dispatch = (item) => {
      const id = _nextId++;
      setItems((prev) => [...prev.slice(-4), { ...item, id }]);
      const timer = setTimeout(() => remove(id), DURATION_MS);
      timersRef.current.set(id, timer);
    };
    return () => {
      _dispatch = null;
    };
  }, [remove]);

  if (items.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 max-w-sm" role="status" aria-live="polite">
      {items.map((item) => {
        const Icon = ICON_MAP[item.variant];
        return (
          <div
            key={item.id}
            className={`flex items-start gap-2 rounded-xl border px-4 py-3 shadow-lg text-sm animate-in slide-in-from-bottom-2 ${STYLE_MAP[item.variant]}`}
          >
            <Icon className="mt-0.5 h-4 w-4 shrink-0" />
            <span className="flex-1">{item.message}</span>
            <button
              type="button"
              className="ml-2 shrink-0 opacity-60 hover:opacity-100 transition-opacity"
              onClick={() => remove(item.id)}
              aria-label="关闭"
            >
              ×
            </button>
          </div>
        );
      })}
    </div>
  );
}
