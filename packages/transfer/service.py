from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from packages.storage.postgres.models import (
    Chapter,
    ChapterVersion,
    Character,
    Foreshadowing,
    MemoryChunk,
    Outline,
    Project,
    TimelineEvent,
    WorldEntry,
)
from packages.storage.postgres.repositories.project_repository import ProjectRepository
from packages.storage.postgres.repositories.project_transfer_job_repository import (
    ProjectTransferJobRepository,
)


class ProjectTransferService:
    def __init__(self, *, db, repo: ProjectTransferJobRepository) -> None:
        self.db = db
        self.repo = repo

    def export_project(
        self,
        *,
        project_id,
        created_by,
        output_dir: str,
        include_chapters: bool = True,
        include_versions: bool = True,
        include_long_term_memory: bool = False,
    ) -> dict:
        job = self.repo.create_job(
            job_type="export",
            project_id=project_id,
            created_by=created_by,
            include_chapters=include_chapters,
            include_versions=include_versions,
            include_long_term_memory=include_long_term_memory,
        )
        self.repo.mark_running(job.id)

        project = ProjectRepository(self.db).get(project_id)
        if project is None:
            self.repo.mark_failed(job.id, error_message="project 不存在")
            raise RuntimeError("project 不存在")

        data = {
            "manifest": {
                "version": "v1",
                "project_id": str(project.id),
                "include_chapters": bool(include_chapters),
                "include_versions": bool(include_versions),
                "include_long_term_memory": bool(include_long_term_memory),
            },
            "project": {
                "title": project.title,
                "genre": project.genre,
                "premise": project.premise,
                "metadata_json": dict(project.metadata_json or {}),
            },
            "outlines": self._dump_rows(select(Outline).where(Outline.project_id == project_id)),
            "characters": self._dump_rows(select(Character).where(Character.project_id == project_id)),
            "world_entries": self._dump_rows(select(WorldEntry).where(WorldEntry.project_id == project_id)),
            "timeline_events": self._dump_rows(select(TimelineEvent).where(TimelineEvent.project_id == project_id)),
            "foreshadowings": self._dump_rows(select(Foreshadowing).where(Foreshadowing.project_id == project_id)),
            "chapters": [],
            "chapter_versions": [],
            "memory_chunks": [],
        }
        if include_chapters:
            chapters = self._dump_rows(select(Chapter).where(Chapter.project_id == project_id))
            data["chapters"] = chapters
            if include_versions:
                chapter_ids = [UUID(str(item["id"])) for item in chapters if item.get("id")]
                if chapter_ids:
                    data["chapter_versions"] = self._dump_rows(
                        select(ChapterVersion).where(ChapterVersion.chapter_id.in_(chapter_ids))
                    )
        if include_long_term_memory:
            data["memory_chunks"] = self._dump_rows_without_embedding(
                select(MemoryChunk).where(MemoryChunk.project_id == project_id)
            )

        output_root = Path(output_dir).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        file_path = output_root / f"project_export_{project.id}.json"
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        file_path.write_text(payload, encoding="utf-8")

        size = file_path.stat().st_size
        checksum = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        self.repo.mark_success(
            job.id,
            target_path=str(file_path),
            size_bytes=size,
            checksum=checksum,
            manifest_json=dict(data.get("manifest") or {}),
        )
        return {
            "job_id": str(job.id),
            "file_path": str(file_path),
            "checksum": checksum,
            "size_bytes": int(size),
        }

    def import_project(self, *, source_path: str, created_by) -> dict:
        job = self.repo.create_job(
            job_type="import",
            project_id=None,
            created_by=created_by,
            source_path=source_path,
            include_chapters=True,
            include_versions=True,
            include_long_term_memory=False,
        )
        self.repo.mark_running(job.id)

        path = Path(source_path).expanduser().resolve()
        if not path.exists():
            self.repo.mark_failed(job.id, error_message="source_path 不存在")
            raise FileNotFoundError(str(path))

        data = json.loads(path.read_text(encoding="utf-8"))
        manifest = dict(data.get("manifest") or {})
        job.include_chapters = bool(manifest.get("include_chapters", True))
        job.include_versions = bool(manifest.get("include_versions", True))
        job.include_long_term_memory = bool(manifest.get("include_long_term_memory", False))
        self.db.commit()
        self.db.refresh(job)
        project_data = dict(data.get("project") or {})
        project = ProjectRepository(self.db).create(
            title=str(project_data.get("title") or "Imported Project"),
            genre=project_data.get("genre"),
            premise=project_data.get("premise"),
            owner_user_id=created_by,
        )
        ProjectRepository(self.db).update(project.id, metadata_json=dict(project_data.get("metadata_json") or {}))

        self._restore_rows(Outline, data.get("outlines"), project.id)
        self._restore_rows(Character, data.get("characters"), project.id)
        self._restore_rows(WorldEntry, data.get("world_entries"), project.id)
        self._restore_rows(TimelineEvent, data.get("timeline_events"), project.id)
        self._restore_rows(Foreshadowing, data.get("foreshadowings"), project.id)

        chapter_id_map: dict[str, UUID] = {}
        for item in list(data.get("chapters") or []):
            obj = Chapter(
                project_id=project.id,
                chapter_no=int(item.get("chapter_no") or 1),
                title=item.get("title"),
                content=item.get("content"),
                summary=item.get("summary"),
                status=item.get("status") or "draft",
                draft_version=int(item.get("draft_version") or 1),
            )
            self.db.add(obj)
            self.db.flush()
            if item.get("id"):
                chapter_id_map[str(item.get("id"))] = obj.id

        for item in list(data.get("chapter_versions") or []):
            raw_chapter_id = str(item.get("chapter_id") or "")
            mapped_id = chapter_id_map.get(raw_chapter_id)
            if mapped_id is None:
                continue
            obj = ChapterVersion(
                chapter_id=mapped_id,
                version_no=int(item.get("version_no") or 1),
                content=item.get("content"),
                summary=item.get("summary"),
                source_agent=item.get("source_agent"),
                source_workflow=item.get("source_workflow"),
                trace_id=item.get("trace_id"),
            )
            self.db.add(obj)

        self._restore_memory_chunks(rows=data.get("memory_chunks"), project_id=project.id)

        self.db.commit()
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        self.repo.mark_success(
            job.id,
            target_path=str(path),
            size_bytes=path.stat().st_size,
            checksum=checksum,
            manifest_json=dict(data.get("manifest") or {}),
            metadata_json={"imported_project_id": str(project.id)},
        )
        return {
            "job_id": str(job.id),
            "project_id": str(project.id),
            "checksum": checksum,
        }

    def _dump_rows_without_embedding(self, stmt) -> list[dict]:
        rows = list(self.db.execute(stmt).scalars().all())
        out: list[dict] = []
        for row in rows:
            item: dict = {}
            for key in row.__table__.columns.keys():
                if key == "embedding":
                    continue
                value = getattr(row, key)
                if isinstance(value, UUID):
                    item[key] = str(value)
                elif hasattr(value, "isoformat"):
                    item[key] = value.isoformat() if value is not None else None
                else:
                    item[key] = value
            out.append(item)
        return out

    def _dump_rows(self, stmt) -> list[dict]:
        rows = list(self.db.execute(stmt).scalars().all())
        out: list[dict] = []
        for row in rows:
            item: dict = {}
            for key in row.__table__.columns.keys():
                value = getattr(row, key)
                if isinstance(value, UUID):
                    item[key] = str(value)
                elif hasattr(value, "isoformat"):
                    item[key] = value.isoformat() if value is not None else None
                else:
                    item[key] = value
            out.append(item)
        return out

    def _restore_rows(self, model_cls, rows, project_id) -> None:
        for item in list(rows or []):
            data = dict(item or {})
            data.pop("id", None)
            data.pop("created_at", None)
            data.pop("updated_at", None)
            data["project_id"] = project_id
            obj = model_cls(**data)
            self.db.add(obj)
        self.db.flush()

    def _restore_memory_chunks(self, *, rows, project_id) -> None:
        for item in list(rows or []):
            data = dict(item or {})
            data.pop("id", None)
            data.pop("created_at", None)
            data.pop("updated_at", None)
            data.pop("embedding", None)
            data["project_id"] = project_id
            raw_source_id = data.get("source_id")
            if raw_source_id:
                try:
                    data["source_id"] = UUID(str(raw_source_id))
                except ValueError:
                    data["source_id"] = None
            data["embedding"] = None
            data["embedding_status"] = "pending"
            obj = MemoryChunk(**data)
            self.db.add(obj)
        self.db.flush()
