from __future__ import annotations

from sqlalchemy import and_, select

from .base import BaseRepository
from packages.storage.postgres.models.character import Character
from packages.storage.postgres.models.character_chapter_asset import CharacterChapterAsset


class CharacterChapterAssetRepository(BaseRepository):
    def get_for_character_chapter(self, *, character_id, chapter_no: int) -> CharacterChapterAsset | None:
        stmt = select(CharacterChapterAsset).where(
            and_(
                CharacterChapterAsset.character_id == character_id,
                CharacterChapterAsset.chapter_no == int(chapter_no),
            )
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_project_chapter(self, *, project_id, chapter_no: int) -> list[CharacterChapterAsset]:
        stmt = (
            select(CharacterChapterAsset)
            .join(Character, Character.id == CharacterChapterAsset.character_id)
            .where(
                Character.project_id == project_id,
                CharacterChapterAsset.chapter_no == int(chapter_no),
            )
        )
        return list(self.db.execute(stmt).scalars().all())

    def upsert(
        self,
        *,
        character_id,
        chapter_no: int,
        inventory_json: dict | None = None,
        wealth_json: dict | None = None,
        auto_commit: bool = True,
    ) -> CharacterChapterAsset:
        row = self.get_for_character_chapter(character_id=character_id, chapter_no=int(chapter_no))
        if row is None:
            row = CharacterChapterAsset(
                character_id=character_id,
                chapter_no=int(chapter_no),
                inventory_json=dict(inventory_json or {}),
                wealth_json=dict(wealth_json or {}),
            )
            self.db.add(row)
        else:
            if inventory_json is not None:
                row.inventory_json = dict(inventory_json)
            if wealth_json is not None:
                row.wealth_json = dict(wealth_json)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row
