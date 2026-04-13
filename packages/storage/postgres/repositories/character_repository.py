from __future__ import annotations

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.character import Character


class CharacterRepository(BaseRepository):
    def create(
        self,
        *,
        project_id,
        name: str,
        role_type: str | None = None,
        age: int | None = None,
        faction: str | None = None,
        profile_json: dict | None = None,
        speech_style_json: dict | None = None,
        arc_status_json: dict | None = None,
        is_canonical: bool = True,
        auto_commit: bool = True,
    ) -> Character:
        row = Character(
            project_id=project_id,
            name=name,
            role_type=role_type,
            age=age,
            faction=faction,
            profile_json=dict(profile_json or {}),
            speech_style_json=dict(speech_style_json or {}),
            arc_status_json=dict(arc_status_json or {}),
            is_canonical=bool(is_canonical),
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get(self, character_id) -> Character | None:
        return self.db.get(Character, character_id)

    def list_by_project(
        self,
        *,
        project_id,
        limit: int = 200,
        canonical_only: bool = False,
    ) -> list[Character]:
        stmt = select(Character).where(Character.project_id == project_id)
        if canonical_only:
            stmt = stmt.where(Character.is_canonical.is_(True))
        stmt = stmt.order_by(Character.updated_at.desc()).limit(max(1, int(limit)))
        return list(self.db.execute(stmt).scalars().all())

    def update(self, character_id, *, auto_commit: bool = True, **fields) -> Character | None:
        row = self.get(character_id)
        if row is None:
            return None
        allowed = {
            "name",
            "role_type",
            "age",
            "faction",
            "profile_json",
            "speech_style_json",
            "arc_status_json",
            "is_canonical",
            "version",
        }
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            if key in {"profile_json", "speech_style_json", "arc_status_json"}:
                setattr(row, key, dict(value))
            elif key == "is_canonical":
                setattr(row, key, bool(value))
            else:
                setattr(row, key, value)

        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def delete(self, character_id, *, auto_commit: bool = True) -> bool:
        row = self.get(character_id)
        if row is None:
            return False
        self.db.delete(row)
        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()
        return True

