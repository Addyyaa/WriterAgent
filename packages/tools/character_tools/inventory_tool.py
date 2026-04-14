from __future__ import annotations

from typing import Any

from packages.storage.postgres.repositories.character_chapter_asset_repository import (
    CharacterChapterAssetRepository,
)
from packages.storage.postgres.repositories.character_repository import CharacterRepository


class CharacterInventoryTool:
    """角色当前物品：优先本章 `character_chapter_assets` 快照，否则回退 `characters.inventory_json`。"""

    def __init__(self, db) -> None:
        self._db = db

    def run(
        self,
        *,
        project_id,
        character_id,
        chapter_no: int | None = None,
    ) -> dict[str, Any]:
        char_repo = CharacterRepository(self._db)
        character = char_repo.get(character_id)
        if character is None:
            return {"found": False, "error": "角色不存在"}
        if str(character.project_id) != str(project_id):
            return {"found": False, "error": "角色不属于该项目"}
        base_inv = dict(getattr(character, "inventory_json", None) or {})
        base_wealth = dict(getattr(character, "wealth_json", None) or {})
        out: dict[str, Any] = {
            "found": True,
            "character_id": str(character_id),
            "chapter_no": chapter_no,
            "source": "character_default",
            "inventory_json": base_inv,
            "wealth_json": base_wealth,
        }
        if chapter_no is None:
            return out
        asset_repo = CharacterChapterAssetRepository(self._db)
        snap = asset_repo.get_for_character_chapter(character_id=character_id, chapter_no=int(chapter_no))
        if snap is None:
            return out
        return {
            "found": True,
            "character_id": str(character_id),
            "chapter_no": int(chapter_no),
            "source": "chapter_snapshot",
            "inventory_json": dict(snap.inventory_json or {}),
            "wealth_json": dict(snap.wealth_json or {}),
        }
