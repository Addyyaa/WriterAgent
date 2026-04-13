"""expand embedding_status enum to support queue/retry/stale

Revision ID: e8f1b2c3d4a5
Revises: d3c6f9a1b2e4
Create Date: 2026-04-07 05:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e8f1b2c3d4a5"
down_revision: Union[str, Sequence[str], None] = "d3c6f9a1b2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for status in ("queued", "retrying", "stale"):
        op.execute(
            sa.text(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_type t
                        JOIN pg_enum e ON t.oid = e.enumtypid
                        WHERE t.typname = 'embedding_status_enum'
                          AND e.enumlabel = '{status}'
                    ) THEN
                        ALTER TYPE embedding_status_enum ADD VALUE '{status}';
                    END IF;
                END
                $$;
                """
            )
        )


def downgrade() -> None:
    # 降级前将新状态归并到旧状态集，避免 CAST 失败。
    op.execute(
        sa.text(
            """
            UPDATE memory_chunks
            SET embedding_status = 'pending'
            WHERE embedding_status IN ('queued', 'retrying', 'stale')
            """
        )
    )

    op.execute(sa.text("ALTER TABLE memory_chunks ALTER COLUMN embedding_status DROP DEFAULT"))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'embedding_status_enum_old') THEN
                    CREATE TYPE embedding_status_enum_old AS ENUM (
                        'pending', 'processing', 'done', 'failed'
                    );
                END IF;
            END
            $$;
            """
        )
    )

    op.execute(
        sa.text(
            """
            ALTER TABLE memory_chunks
            ALTER COLUMN embedding_status
            TYPE embedding_status_enum_old
            USING embedding_status::text::embedding_status_enum_old
            """
        )
    )

    op.execute(sa.text("DROP TYPE IF EXISTS embedding_status_enum"))
    op.execute(sa.text("ALTER TYPE embedding_status_enum_old RENAME TO embedding_status_enum"))
    op.execute(
        sa.text(
            "ALTER TABLE memory_chunks ALTER COLUMN embedding_status SET DEFAULT 'pending'"
        )
    )
