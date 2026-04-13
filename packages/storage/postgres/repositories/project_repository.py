from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.project import Project


class ProjectRepository(BaseRepository):
    def create(
        self,
        title: str,
        genre: str | None = None,
        premise: str | None = None,
        owner_user_id=None,
    ) -> Project:
        project = Project(
            owner_user_id=owner_user_id,
            title=title,
            genre=genre,
            premise=premise,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    def get(self, project_id) -> Project | None:
        return self.db.get(Project, project_id)

    def list_all(self) -> list[Project]:
        stmt = select(Project).order_by(Project.created_at.desc())
        return list(self.db.execute(stmt).scalars().all())

    def list_by_owner(self, owner_user_id) -> list[Project]:
        stmt = (
            select(Project)
            .where(Project.owner_user_id == owner_user_id)
            .order_by(Project.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def update(
        self,
        project_id,
        *,
        title: str | None = None,
        genre: str | None = None,
        premise: str | None = None,
        metadata_json: dict | None = None,
        owner_user_id=None,
        auto_commit: bool = True,
    ) -> Project | None:
        row = self.get(project_id)
        if row is None:
            return None
        if title is not None:
            row.title = title
        if genre is not None:
            row.genre = genre
        if premise is not None:
            row.premise = premise
        if metadata_json is not None:
            row.metadata_json = dict(metadata_json)
        if owner_user_id is not None:
            row.owner_user_id = owner_user_id
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def delete(self, project_id, *, auto_commit: bool = True) -> bool:
        row = self.get(project_id)
        if row is None:
            return False
        self.db.delete(row)
        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()
        return True
