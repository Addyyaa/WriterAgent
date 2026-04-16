import { proxyBackend } from "@/server/bff/http";

/** BFF：代理管理员查询单次 LLM 请求的 system/user 审计快照（对应日志中的 llm_task_id）。 */
export async function GET(_: Request, context: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await context.params;
  const normalized = encodeURIComponent(String(taskId || "").trim());
  return proxyBackend({ path: `/v2/system/llm-prompts/${normalized}`, method: "GET" });
}
