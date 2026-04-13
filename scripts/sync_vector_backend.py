"""把 PostgreSQL memory_chunks 同步到当前配置的向量后端。

用法示例：
    ./venv/bin/python scripts/sync_vector_backend.py --project-id <uuid>
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy.orm import sessionmaker

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from packages.memory.long_term.runtime_config import MemoryRuntimeConfig
from packages.retrieval.vector.factory import create_vector_store
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository
from scripts._db_engine import create_engine_with_driver_fallback

_DEFAULT_DATABASE_URL = "postgresql+psycopg2://addy:sf123123@localhost:5432/writer_agent_db"


def main() -> int:
    parser = argparse.ArgumentParser(description="同步 memory_chunks 到向量后端")
    parser.add_argument("--project-id", required=True, help="项目 ID")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    if args.batch_size <= 0:
        raise ValueError("batch-size 必须大于 0")

    db_url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
    echo = os.environ.get("SQL_ECHO", "").lower() in {"1", "true", "yes"}
    engine = create_engine_with_driver_fallback(db_url, echo=echo)
    SessionLocal = sessionmaker(bind=engine)

    runtime_cfg = MemoryRuntimeConfig.from_env()

    db = SessionLocal()
    try:
        memory_repo = MemoryChunkRepository(db)
        vector_store = create_vector_store(memory_repo=memory_repo, runtime_config=runtime_cfg.retrieval)

        offset = 0
        total = 0
        while True:
            rows = memory_repo.list_by_project(
                project_id=args.project_id,
                limit=args.batch_size,
                offset=offset,
                embedding_status="done",
                sort_by="created_at_desc",
            )
            if not rows:
                break

            items = []
            for row in rows:
                if row.embedding is None:
                    continue
                items.append(
                    {
                        "id": str(row.id),
                        "project_id": row.project_id,
                        "source_type": row.source_type,
                        "source_id": row.source_id,
                        "chunk_type": row.chunk_type,
                        "text": row.chunk_text or "",
                        "metadata_json": row.metadata_json or {},
                        "embedding": list(row.embedding),
                        "embedding_status": row.embedding_status,
                    }
                )

            if items:
                vector_store.upsert(items)
                total += len(items)

            offset += len(rows)

        print(
            f"sync finished: project_id={args.project_id}, backend={runtime_cfg.retrieval.vector.backend}, upserted={total}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
