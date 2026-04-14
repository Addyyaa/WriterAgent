from sqlalchemy import func, select

from .base import BaseRepository
from packages.storage.postgres.models.chapter import Chapter
from packages.storage.postgres.models.chapter_version import ChapterVersion


class ChapterRepository(BaseRepository):

    # =========================
    # 自动分配章节号
    # =========================
    def get_next_chapter_no(self, project_id):
        stmt = select(func.max(Chapter.chapter_no)).where(
            Chapter.project_id == project_id
        )
        max_no = self.db.execute(stmt).scalar()
        return 1 if max_no is None else max_no + 1

    # =========================
    # 创建章节
    # =========================
    def create(self, project_id, title=None, content=None, created_by=None):
        chapter_no = self.get_next_chapter_no(project_id)

        chapter = Chapter(
            project_id=project_id,
            chapter_no=chapter_no,
            title=title,
            content=content,
            created_by=created_by,
            status="draft",
        )
        self.db.add(chapter)
        self.db.commit()
        self.db.refresh(chapter)
        return chapter

    # =========================
    # 获取章节
    # =========================
    def get(self, chapter_id):
        return self.db.get(Chapter, chapter_id)

    # =========================
    # 获取章节列表
    # =========================
    def list_by_project(self, project_id):
        stmt = (
            select(Chapter)
            .where(Chapter.project_id == project_id)
            .order_by(Chapter.chapter_no.asc())
        )
        return self.db.execute(stmt).scalars().all()

    def get_by_project_chapter_no(self, project_id, chapter_no: int):
        stmt = select(Chapter).where(
            Chapter.project_id == project_id,
            Chapter.chapter_no == chapter_no,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def find_by_project_title(self, project_id, title: str) -> Chapter | None:
        """按章节标题查找：先精确（忽略大小写与首尾空白），再子串 ilike。"""
        raw = str(title or "").strip()
        if not raw:
            return None
        stmt_exact = (
            select(Chapter)
            .where(
                Chapter.project_id == project_id,
                Chapter.title.isnot(None),
                func.lower(func.trim(Chapter.title)) == raw.lower(),
            )
            .order_by(Chapter.chapter_no.asc())
            .limit(1)
        )
        row = self.db.execute(stmt_exact).scalar_one_or_none()
        if row is not None:
            return row
        stmt_like = (
            select(Chapter)
            .where(
                Chapter.project_id == project_id,
                Chapter.title.isnot(None),
                Chapter.title.ilike(f"%{raw}%"),
            )
            .order_by(Chapter.chapter_no.asc())
            .limit(1)
        )
        return self.db.execute(stmt_like).scalar_one_or_none()

    # =========================
    # 更新内容（核心）
    # =========================
    def update_content(self, chapter_id, content, summary=None):
        chapter = self.get(chapter_id)
        if not chapter:
            return None

        # 👉 更新前先做版本快照（关键设计）
        self.create_version(
            chapter_id=chapter.id,
            content=chapter.content,
            summary=chapter.summary,
            source_agent="system_backup",
        )

        chapter.content = content
        if summary:
            chapter.summary = summary

        chapter.draft_version += 1

        self.db.commit()
        self.db.refresh(chapter)
        return chapter

    # =========================
    # 发布章节
    # =========================
    def publish(self, chapter_id):
        chapter = self.get(chapter_id)
        if not chapter:
            return None

        chapter.status = "published"

        self.db.commit()
        return chapter

    # =========================
    # 删除章节
    # =========================
    def delete(self, chapter_id):
        chapter = self.get(chapter_id)
        if not chapter:
            return False

        self.db.delete(chapter)
        self.db.commit()
        return True

    # =========================
    # 创建版本（关键）
    # =========================
    def create_version(
        self,
        chapter_id,
        content,
        summary=None,
        source_agent=None,
        source_workflow=None,
        trace_id=None,
    ):
        stmt = (
            select(ChapterVersion.version_no)
            .where(ChapterVersion.chapter_id == chapter_id)
            .order_by(ChapterVersion.version_no.desc())
            .limit(1)
        )

        last_version = self.db.execute(stmt).scalar()
        next_version = 1 if last_version is None else last_version + 1

        version = ChapterVersion(
            chapter_id=chapter_id,
            version_no=next_version,
            content=content,
            summary=summary,
            source_agent=source_agent,
            source_workflow=source_workflow,
            trace_id=trace_id,
        )

        self.db.add(version)
        self.db.commit()
        return version

    def delete_version(self, version_id, *, auto_commit: bool = True) -> bool:
        version = self.db.get(ChapterVersion, version_id)
        if not version:
            return False
        self.db.delete(version)
        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()
        return True

    def save_generated_draft(
        self,
        *,
        project_id,
        chapter_no: int | None,
        title: str | None,
        content: str | None,
        summary: str | None,
        source_agent: str,
        source_workflow: str,
        trace_id: str | None,
    ) -> tuple[Chapter, ChapterVersion, bool]:
        """
        保存 AI 生成章节并写入版本快照。

        返回：
            (chapter, version, created_new_chapter)
        """
        created_new = False
        effective_chapter_no = (
            self.get_next_chapter_no(project_id)
            if chapter_no is None
            else int(chapter_no)
        )

        chapter = self.get_by_project_chapter_no(
            project_id=project_id,
            chapter_no=effective_chapter_no,
        )

        if chapter is None:
            chapter = Chapter(
                project_id=project_id,
                chapter_no=effective_chapter_no,
                title=title,
                content=content,
                summary=summary,
                status="draft",
                draft_version=1,
            )
            self.db.add(chapter)
            self.db.flush()
            created_new = True
        else:
            chapter.title = title
            chapter.content = content
            chapter.summary = summary
            chapter.status = "draft"
            chapter.draft_version = int(chapter.draft_version or 1) + 1

        stmt = (
            select(func.max(ChapterVersion.version_no))
            .where(ChapterVersion.chapter_id == chapter.id)
        )
        max_version = self.db.execute(stmt).scalar()
        next_version_no = 1 if max_version is None else int(max_version) + 1

        version = ChapterVersion(
            chapter_id=chapter.id,
            version_no=next_version_no,
            content=chapter.content,
            summary=chapter.summary,
            source_agent=source_agent,
            source_workflow=source_workflow,
            trace_id=trace_id,
        )
        self.db.add(version)
        self.db.commit()
        self.db.refresh(chapter)
        self.db.refresh(version)
        return chapter, version, created_new

    def restore_generated_draft(
        self,
        *,
        chapter_id,
        title: str | None,
        content: str | None,
        summary: str | None,
        draft_version: int,
        auto_commit: bool = True,
    ) -> Chapter | None:
        chapter = self.get(chapter_id)
        if chapter is None:
            return None
        chapter.title = title
        chapter.content = content
        chapter.summary = summary
        chapter.draft_version = int(draft_version)
        if auto_commit:
            self.db.commit()
            self.db.refresh(chapter)
        else:
            self.db.flush()
        return chapter

    # =========================
    # 获取版本列表
    # =========================
    def list_versions(self, chapter_id):
        stmt = (
            select(ChapterVersion)
            .where(ChapterVersion.chapter_id == chapter_id)
            .order_by(ChapterVersion.version_no.desc())
        )
        return self.db.execute(stmt).scalars().all()

    # =========================
    # 回滚到某个版本（🔥高级功能）
    # =========================
    def rollback_to_version(self, chapter_id, version_no):
        stmt = (
            select(ChapterVersion)
            .where(
                ChapterVersion.chapter_id == chapter_id,
                ChapterVersion.version_no == version_no,
            )
        )
        version = self.db.execute(stmt).scalar_one_or_none()

        if not version:
            return None

        chapter = self.get(chapter_id)

        # 👉 回滚前再备份当前版本
        self.create_version(
            chapter_id=chapter.id,
            content=chapter.content,
            summary=chapter.summary,
            source_agent="rollback_backup",
        )

        chapter.content = version.content
        chapter.summary = version.summary

        self.db.commit()
        return chapter
