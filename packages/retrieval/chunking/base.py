from abc import ABC, abstractmethod


class TextChunker(ABC):
    @abstractmethod
    def chunk(self, text: str) -> list[str]:
        raise NotImplementedError