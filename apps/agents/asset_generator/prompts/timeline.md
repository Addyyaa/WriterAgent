# Task: Narrative Rhythm Blueprint（叙事节奏蓝图设计）

时间线不是事件的流水账，而是一张**叙事心电图**——记录故事的心跳节奏。每个节点标记着一次不可逆转的状态变迁。

## 故事信息
{{ context }}

## Design Framework

### 1. Event Classification（事件分类学）

参考 Robert McKee 的故事事件分级：
- **Inciting Incident（激励事件）**: 打破均衡的第一推动力
- **Progressive Complication（递进复杂化）**: 每次尝试解决问题反而制造更大的问题
- **Crisis（危机）**: 角色被迫在两个不可调和的价值之间做出选择
- **Climax（高潮）**: 选择的后果不可逆转地改变了故事走向
- **Resolution（解决）**: 新秩序的确立

### 2. Rhythm Control（节奏控制）

- 事件间距不能均匀——前期可以慢铺垫（2-3章一个节点），中后期必须加速（每章一个节点）
- 相邻事件的"情感极性"应交替变化（希望→绝望→新希望→更大的绝望）
- 至少安排一个"虚假胜利"（False Victory）——让角色以为问题解决了，随后揭示更深层的危机

### 3. Character-Event Binding（角色-事件绑定）

每个事件必须至少改变一个角色的内在状态（信念动摇、关系破裂、能力觉醒等），纯外部事件没有叙事价值。

## Constraints

- chapter_no 从 1 开始，间距应反映叙事节奏（非等间隔）
- 每个事件必须推动主线剧情，不包含纯支线事件
- 事件之间必须有因果关系链（A 导致 B，B 导致 C）
- 最后一个事件必须开启新悬念或未解的矛盾

## Output Format (JSON)

{
  "events": [
    {
      "chapter_no": number,
      "title": "string（事件标题，4-8字）",
      "event_type": "string（inciting / complication / crisis / climax / resolution）",
      "description": "string（事件描述：发生了什么 → 角色被迫如何选择 → 导致什么后果，50-100字）",
      "location": "string（发生地点）",
      "characters_involved": "string（相关角色，逗号分隔）",
      "state_change": "string（这个事件不可逆转地改变了什么？一句话）"
    }
  ],
  "causal_chain": "string（用 → 连接的因果链条，概括整条时间线的逻辑流）"
}
