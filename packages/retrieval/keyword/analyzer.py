from __future__ import annotations

import re


class SimpleAnalyzer:
    """
    轻量统一分词器。

    设计目标：
    1) 英文/数字串保持常规 token；
    2) 中文不再把整句当成一个 token，默认补充 n-gram（2/3）；
    3) 若环境安装了 jieba，则优先使用 jieba 的中文词粒度，再补 n-gram 兜底。
    """

    _LATIN_RE = re.compile(r"[a-z0-9]{2,}", re.IGNORECASE)
    _CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")

    try:
        import jieba as _jieba  # type: ignore
    except Exception:  # pragma: no cover - 可选依赖，不强制安装
        _jieba = None

    def tokenize(self, text: str) -> list[str]:
        if not isinstance(text, str):
            return []
        raw = text.strip()
        if not raw:
            return []

        tokens: list[str] = []
        seen: set[str] = set()

        def add_token(token: str) -> None:
            item = token.strip().lower()
            if len(item) < 2:
                return
            if item in seen:
                return
            seen.add(item)
            tokens.append(item)

        # 英文/数字 token
        for token in self._LATIN_RE.findall(raw):
            add_token(token)

        # 中文 token
        if self._jieba is not None:
            for token in self._jieba.lcut(raw):
                if self._CJK_RE.fullmatch(token or ""):
                    add_token(token)

        for seq in self._CJK_RE.findall(raw):
            add_token(seq)
            # 2/3-gram 兜底，避免整句匹配导致关键词检索失真
            for n in (2, 3):
                if len(seq) < n:
                    continue
                for i in range(0, len(seq) - n + 1):
                    add_token(seq[i : i + n])

        return tokens
