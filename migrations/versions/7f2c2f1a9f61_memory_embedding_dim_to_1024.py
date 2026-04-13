"""memory embedding dim to 1024

Revision ID: 7f2c2f1a9f61
Revises: c98141f97df1
Create Date: 2026-04-03 10:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7f2c2f1a9f61"
down_revision: Union[str, Sequence[str], None] = "c98141f97df1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 先删除向量索引，避免后续 ALTER TYPE 受阻
    op.drop_index("idx_embedding", table_name="memory_chunks")

    # 对维度不为 1024 的历史向量做降级处理，避免类型转换失败。
    # 这些数据需要后续重算 embedding，因此状态回退到 pending。
    op.execute(
        sa.text(
            """
            UPDATE memory_chunks
            SET embedding = NULL,
                embedding_status = 'pending'
            WHERE embedding IS NOT NULL
              AND vector_dims(embedding) <> 1024
            """
        )
    )

    # 调整列类型到 vector(1024)
    op.execute(
        sa.text(
            """
            ALTER TABLE memory_chunks
            ALTER COLUMN embedding TYPE vector(1024)
            USING embedding::vector(1024)
            """
        )
    )

    # 重建向量索引
    op.create_index(
        "idx_embedding",
        "memory_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="ivfflat",
        postgresql_with={"lists": 100},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("idx_embedding", table_name="memory_chunks")

    op.execute(
        sa.text(
            """
            ALTER TABLE memory_chunks
            ALTER COLUMN embedding TYPE vector(1536)
            USING embedding::vector(1536)
            """
        )
    )

    op.create_index(
        "idx_embedding",
        "memory_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="ivfflat",
        postgresql_with={"lists": 100},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

