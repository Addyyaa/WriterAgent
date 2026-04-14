# Task: Narrative Arc Blueprint（叙事弧光蓝图设计）

将故事前提转化为一份完整的**叙事引擎蓝图**——它不是简单的事件时间表，而是一张驱动故事持续运转的**矛盾动力图**。

## 故事信息
{{ context }}

## Design Framework

使用经典的 **Three-Act → Five-Phase** 混合结构：

1. **Phase I · 引擎启动（Status Quo Disruption）**
   - 用最短的篇幅建立"正常世界"，然后打碎它
   - 关键问题：什么事件让主角不可能继续维持现状？

2. **Phase II · 递进压缩（Escalation & Compression）**
   - 每个阶段的赌注（Stakes）必须高于前一个
   - 引入"盟友与敌人"——但至少一个盟友要有隐藏议程

3. **Phase III · 黑暗低谷（Dark Night of the Soul）**
   - 主角必须经历一次核心信念的崩塌
   - 此阶段决定整个故事的情感深度

4. **Phase IV · 觉醒重构（Reconstruction）**
   - 主角用新的认知重新审视之前的线索
   - 前文的伏笔在此阶段开始回收

5. **Phase V · 高潮与新秩序（Climax & New Order）**
   - 外部冲突的解决必须与内心转变同步
   - 预留一个未解之谜，为续作埋下种子

## Constraints

- 每个阶段必须有明确的**核心矛盾**和**阶段终止条件**
- 不要写具体的对话或正文描写
- 阶段之间的因果链必须清晰可追溯

## Output Format (JSON)

{
  "title": "string（大纲标题，如：第一卷·XXX）",
  "content": "string（大纲正文，每个阶段独占一段，格式为：\n阶段N·阶段名称：核心矛盾描述 → 阶段终止条件）",
  "promise": "string（这个故事向读者做出的核心承诺，一句话）",
  "central_question": "string（贯穿全卷的核心悬念问题）"
}
