"use client";

import type { ReactNode } from "react";

import type { ProjectRole } from "@/generated/api/types";
import { canAccess } from "@/modules/rbac/rules";

export function RbacGate({
  role,
  minRole,
  fallback,
  children
}: {
  role: ProjectRole;
  minRole: ProjectRole;
  fallback?: ReactNode;
  children: ReactNode;
}) {
  if (!canAccess(role, minRole)) {
    return <>{fallback ?? null}</>;
  }
  return <>{children}</>;
}
