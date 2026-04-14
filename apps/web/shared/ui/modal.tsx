"use client";

import { useEffect } from "react";
import type { ReactNode } from "react";

import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";

type ModalProps = {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  widthClassName?: string;
};

export function Modal({ open, title, onClose, children, footer, widthClassName = "max-w-2xl" }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-ink/45 px-4 backdrop-blur-sm" onClick={onClose}>
      <Card
        className={`w-full ${widthClassName} max-h-[88vh] overflow-hidden border-white/25 bg-white/95`}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-ink/10 px-5 py-4">
          <h3 className="font-[var(--font-display)] text-xl font-semibold text-ink">{title}</h3>
          <Button variant="ghost" size="sm" type="button" onClick={onClose}>
            关闭
          </Button>
        </header>
        <div className="max-h-[62vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer ? <footer className="border-t border-ink/10 px-5 py-4">{footer}</footer> : null}
      </Card>
    </div>
  );
}
