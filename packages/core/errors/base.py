from __future__ import annotations


class CoreError(RuntimeError):
    """WriterAgent 横切能力的统一异常基类。"""


class CoreConfigError(CoreError):
    """配置非法、缺失或冲突。"""


class CoreInputError(CoreError):
    """输入参数不合法。"""


class CoreUnavailableError(CoreError):
    """外部依赖不可用。"""


class CoreTimeoutError(CoreError):
    """调用超时。"""


class CoreDataError(CoreError):
    """数据格式或数据契约不满足预期。"""
