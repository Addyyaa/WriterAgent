import type { ProjectRole } from "@/generated/api/types";

const rank: Record<ProjectRole, number> = {
  viewer: 10,
  editor: 20,
  owner: 30,
  admin: 40
};

export function canAccess(role: ProjectRole, minRole: ProjectRole): boolean {
  return rank[role] >= rank[minRole];
}
