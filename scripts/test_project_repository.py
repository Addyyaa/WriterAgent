"""本地调试脚本：需能解析仓库根下的 ``packages`` 包。"""

from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.storage.postgres.repositories.project_repository import ProjectRepository

DATABASE_URL = "postgresql+psycopg2://addy:sf123123@localhost:5432/writer_agent_db"

engine = create_engine(DATABASE_URL, echo=True)
SessionLocal = sessionmaker(bind=engine)


def main():
    db = SessionLocal()
    try:
        repo = ProjectRepository(db)

        project = repo.create(
            title="测试项目",
            genre="奇幻",
            premise="一个少年在废墟世界中寻找真相。"
        )

        print("创建成功：", project.id, project.title)

        result = repo.get(project.id)
        print("查询成功：", result.id, result.title)

        all_projects = repo.list_all()
        print("项目总数：", len(all_projects))

    finally:
        db.close()


if __name__ == "__main__":
    main()