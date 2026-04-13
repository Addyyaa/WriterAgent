from __future__ import annotations

from typing import Any

from packages.storage.postgres.repositories.session_repository import SessionRepository


class SessionService:
    def __init__(self, *, repo: SessionRepository) -> None:
        self.repo = repo

    def create(self, *, project_id, user_id=None, title: str | None = None, metadata_json: dict | None = None):
        return self.repo.create_session(
            project_id=project_id,
            user_id=user_id,
            title=title,
            metadata_json=metadata_json,
        )

    def summarize(self, *, session_id, max_items: int = 20) -> str:
        rows = self.repo.list_messages(session_id=session_id, limit=max(1, int(max_items)), ascending=False)
        rows = list(reversed(rows))
        if not rows:
            summary = "(empty session)"
            self.repo.update_session(session_id, summary=summary)
            return summary

        user_msgs = [str(item.content).strip() for item in rows if str(item.role) == "user" and str(item.content).strip()]
        assistant_msgs = [
            str(item.content).strip()
            for item in rows
            if str(item.role) == "assistant" and str(item.content).strip()
        ]
        summary = (
            f"会话共 {len(rows)} 条消息；"
            f"用户重点 {min(len(user_msgs), 3)} 条："
            + " | ".join(user_msgs[-3:])
            + "；"
            f"助手输出 {min(len(assistant_msgs), 2)} 条："
            + " | ".join(assistant_msgs[-2:])
        )
        self.repo.update_session(session_id, summary=summary)
        return summary

    def to_chat_turns(self, *, session_id, max_messages: int = 40) -> list[dict[str, Any]]:
        rows = self.repo.list_messages(
            session_id=session_id,
            limit=max(1, int(max_messages)),
            ascending=True,
        )
        turns: list[dict[str, Any]] = []
        for item in rows:
            role = str(item.role)
            if role not in {"system", "user", "assistant", "tool"}:
                role = "user"
            turns.append(
                {
                    "role": role,
                    "content": str(item.content or ""),
                    "metadata": dict(item.metadata_json or {}),
                }
            )
        return turns
