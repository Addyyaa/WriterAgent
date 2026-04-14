# Task: Character Constellation Design（角色星座设计）

设计角色不是创建一组孤立的人物卡片，而是构建一个**角色力学系统**——每个角色都是其他角色的镜像、催化剂或对立面。

## 故事信息
{{ context }}

## Design Methodology

### 1. Narrative Function First（叙事功能优先）

在设计角色外表和性格之前，先确定每个角色在故事引擎中的**功能槽位**：
- **Catalyst（催化剂）**: 谁推动主角不得不行动？
- **Mirror（镜像）**: 谁展示了主角的另一种可能性？
- **Threshold Guardian（门槛守护者）**: 谁阻挡在主角和目标之间？
- **Shadow（阴影）**: 谁体现了主角拒绝面对的恐惧？

### 2. Wound → Want → Need（创伤 → 欲望 → 真正需要）

每个核心角色都必须有：
- **Wound（旧伤）**: 过去的什么经历塑造了他/她？
- **Want（外在欲望）**: 他/她声称自己想要什么？
- **Need（内在需要）**: 他/她真正需要但尚未意识到的是什么？
- Want 和 Need 之间的冲突是角色弧光的发动机。

### 3. Relationship Tension Matrix（关系张力矩阵）

角色之间的关系不能是单一维度的"朋友/敌人"。至少包含一组：
- 表面同盟但暗含竞争的关系
- 表面对立但深层共鸣的关系

## Constraints

- 至少包含 1 个 protagonist（催化剂功能）、1 个 antagonist（阴影功能）
- 每个角色的 motivation 必须可追溯到故事前提
- 禁止设计没有叙事功能的装饰性角色
- 角色名字应与故事类型的文化语境匹配

## Output Format (JSON)

{
  "characters": [
    {
      "name": "string（角色姓名）",
      "role_type": "protagonist / antagonist / supporting",
      "narrative_function": "string（catalyst / mirror / threshold_guardian / shadow / mentor）",
      "faction": "string（所属阵营或组织）",
      "age": number,
      "wound": "string（核心创伤，一句话）",
      "want": "string（外在欲望）",
      "need": "string（内在需要）",
      "personality": "string（2-3个性格关键词）",
      "motivation": "string（驱动行动的核心动机）"
    }
  ],
  "tension_pairs": [
    {
      "characters": ["string", "string"],
      "surface_relation": "string（表面关系）",
      "hidden_tension": "string（深层张力）"
    }
  ]
}
