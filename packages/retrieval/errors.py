from __future__ import annotations

# 兼容层说明：
# retrieval 保留领域错误命名，对外接口不变；
# 错误语义基类已统一挂载到 packages.core.errors。
from packages.core.errors import (
    CoreConfigError,
    CoreDataError,
    CoreError,
    CoreInputError,
    CoreTimeoutError,
    CoreUnavailableError,
)


class RetrievalError(CoreError):
    """Retrieval 领域通用异常基类。"""


class RetrievalConfigError(CoreConfigError, RetrievalError):
    """配置非法或缺失。"""


class RetrievalInputError(CoreInputError, RetrievalError):
    """输入参数非法。"""


class RetrieverUnavailableError(CoreUnavailableError, RetrievalError):
    """检索器未就绪或不可用。"""


class RetrievalTimeoutError(CoreTimeoutError, RetrievalError):
    """检索超时。"""


class RetrievalDataError(CoreDataError, RetrievalError):
    """候选数据格式错误或不完整。"""
