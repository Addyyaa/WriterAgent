from abc import ABC, abstractmethod

class EmbeddingProvider(ABC):
    """
    抽象基类：EmbeddingProvider

    用于定义文本嵌入（embeddings）提供者的统一接口。
    子类应实现以下两个方法，用于将文本输入转换为向量表示，
    以支持检索、相似度计算等场景。

    方法:
        embed_texts(texts: list[str]) -> list[list[float]]:
            将文本列表批量转换为嵌入向量列表。每个字符串被编码为浮点数向量。

        embed_query(text: str) -> list[float]:
            将单条查询文本转换为单个嵌入向量。常用于检索的查询输入。
    """

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        输入多个文本，返回对应的嵌入向量列表。

        参数:
            texts (list[str]): 待转换的文本列表。

        返回:
            list[list[float]]: 每个文本对应的嵌入向量（浮点数列表）。
        """
        raise NotImplementedError

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """
        输入单个查询文本，返回其嵌入向量。

        参数:
            text (str): 查询字符串。

        返回:
            list[float]: 查询文本的嵌入向量（浮点数列表）。
        """
        raise NotImplementedError