from __future__ import annotations

from packages.core.utils import ensure_non_empty_string
from packages.llm.embeddings.base import EmbeddingProvider


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
    ) -> None:
        clean_api_key = ensure_non_empty_string(api_key, field_name="api_key")
        clean_model = ensure_non_empty_string(model, field_name="model")
        try:
            from openai import OpenAI
        except Exception as exc:
            raise RuntimeError(
                "未安装 openai 依赖，无法启用 openai_compatible embedding provider。"
            ) from exc

        self.client = OpenAI(
            api_key=clean_api_key,
            base_url=base_url,
        )
        self.model = clean_model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        cleaned_texts = [ensure_non_empty_string(item, field_name="texts.item") for item in texts]

        response = self.client.embeddings.create(
            model=self.model,
            input=cleaned_texts,
        )
        return [item.embedding for item in response.data]

    def embed_query(self, text: str) -> list[float]:
        clean_text = ensure_non_empty_string(text, field_name="text")
        response = self.client.embeddings.create(
            model=self.model,
            input=[clean_text],
        )
        return response.data[0].embedding
