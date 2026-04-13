"""WriterAgent 核心横切能力。

该包只承载跨业务复用的基础设施能力：
- config: 环境变量读取与配置兜底
- errors: 统一错误语义层
- logging: 结构化日志与指标计数
- tracing: request/trace 上下文
- types: 通用类型别名
- utils: 无业务耦合工具函数
"""

from packages.core.logging import StructuredObservability

__all__ = [
    "StructuredObservability",
]
