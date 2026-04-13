"""
PostgreSQL 扩展相关 SQLAlchemy 类型。

``PgVector`` 映射 pgvector 的 ``vector(n)`` 类型；使用前需在数据库中执行
``CREATE EXTENSION IF NOT EXISTS vector``。
"""

from sqlalchemy.types import UserDefinedType


class PgVector(UserDefinedType):
    """
    ``vector(dimensions)`` 列类型，用于嵌入向量存储与相似度检索。

    绑定/结果处理依赖驱动与 pgvector；主要用于元数据、迁移与 DDL 生成。
    """

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_kw: object) -> str:
        return f"vector({self.dimensions})"
