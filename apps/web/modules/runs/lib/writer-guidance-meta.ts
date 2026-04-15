/**
 * writer_draft 步骤 output_json.writer_guidance 的兼容解析。
 * 新链路使用 prompt_payload_via_assembler；旧版曾用 has_guidance_text 表示是否注入 Markdown 护栏。
 */

export type WriterGuidanceMeta = {
  style_hint?: string | null;
  working_notes_count?: number;
  /** 章节草稿 user 负载已由 PromptPayloadAssembler 分区构造 */
  prompt_payload_via_assembler?: boolean;
  /**
   * @deprecated 是否曾附加 Markdown 护栏全文；新链路恒为 false
   */
  has_guidance_text?: boolean;
};

/** 是否走后端 Assembler 分区上下文（优先读 prompt_payload_via_assembler） */
export function writerPayloadUsesAssembler(wg: unknown): boolean {
  if (!wg || typeof wg !== "object") return false;
  const o = wg as Record<string, unknown>;
  if (typeof o.prompt_payload_via_assembler === "boolean") {
    return o.prompt_payload_via_assembler;
  }
  return o.has_guidance_text !== true;
}
