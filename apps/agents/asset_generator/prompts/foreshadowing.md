# Task: Foreshadowing Architecture（伏笔架构设计）

伏笔是作者与读者之间的"延时博弈"——在埋设时，读者看到的是无害的细节；在回收时，细节突然翻转为关键证据，产生**认知重构的快感**。

## 故事信息
{{ context }}

## Design Methodology

### 1. Foreshadowing Taxonomy（伏笔类型学）

- **Structural Foreshadowing（结构伏笔）**: 通过叙事结构暗示（如：开篇的异常细节在结尾成为关键线索）
- **Character Foreshadowing（角色伏笔）**: 通过角色的"反常"行为暗示其隐藏动机或身份
- **Environmental Foreshadowing（环境伏笔）**: 通过场景描写暗示即将发生的事件（暴风雨前的死寂）
- **Dialogue Foreshadowing（台词伏笔）**: 角色无意间说出的话在未来获得新含义

### 2. Hitchcock's Bomb Theory（希区柯克炸弹理论）

- 有些伏笔是"桌下的炸弹"——读者知道危险存在，角色不知道 → 产生**悬念**
- 有些伏笔是"抽屉里的枪"——读者和角色都不知道 → 回收时产生**惊奇**
- 设计时应混合使用两种策略

### 3. Callback Distance（回收距离）

- **短线伏笔**（3-5章回收）: 维持阅读节奏，让读者有"我注意到了"的满足感
- **长线伏笔**（10+章回收）: 制造"原来如此"的震撼感，但埋设时必须足够自然
- 设计时应混合短线和长线，确保每 2-3 章都有伏笔回收

### 4. Plausible Deniability（合理否认性）

伏笔的埋设必须满足：首次阅读时有"合理的无害解释"，二次阅读时才显露真实意图。如果读者第一遍就看穿了，说明埋得太浅。

## Constraints

- 埋设章节必须早于回收章节，短线间隔 ≥ 3 章
- 每条伏笔必须有明确的"表面含义"和"真实含义"
- 禁止设计与故事前提无关的伏笔
- planted_content 应是读者视角可感知的具体细节，不是抽象的"暗示"

## Output Format (JSON)

{
  "items": [
    {
      "planted_chapter": number,
      "type": "string（structural / character / environmental / dialogue）",
      "planted_content": "string（埋设内容——读者视角看到的表象，具体且自然，30-60字）",
      "surface_meaning": "string（表面的无害解释）",
      "true_meaning": "string（回收时揭示的真正含义）",
      "expected_payoff": "string（回收场景描述——怎样的情境下揭示真相，20-50字）",
      "payoff_chapter": number,
      "emotional_target": "string（回收时期望读者产生的情感反应：震惊/恍然大悟/心痛/敬畏）"
    }
  ],
  "strategy_note": "string（整体伏笔策略说明：短线与长线的分布、悬念与惊奇的平衡）"
}
