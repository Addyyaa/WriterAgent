from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class _YamlLine:
    indent: int
    content: str


def parse_simple_yaml(text: str) -> dict[str, Any]:
    """
    解析受限 YAML 子集（mapping/list/scalar）。

    说明：
    - 仅用于项目内受控配置文件（strategy.yaml / skills.yaml）。
    - 不依赖外部库，避免把 PyYAML 作为运行时必选项。
    """
    lines = _tokenize(text)
    if not lines:
        return {}

    node, pos = _parse_node(lines, 0, lines[0].indent)
    if pos != len(lines):
        raise ValueError("YAML 解析未完全消费输入")
    if not isinstance(node, dict):
        raise ValueError("YAML 顶层必须是对象")
    return node


def _tokenize(text: str) -> list[_YamlLine]:
    rows: list[_YamlLine] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        stripped = line.lstrip(" ")
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)
        rows.append(_YamlLine(indent=indent, content=stripped))
    return rows


def _parse_node(lines: list[_YamlLine], pos: int, indent: int) -> tuple[Any, int]:
    if pos >= len(lines):
        return {}, pos

    if lines[pos].content.startswith("- "):
        out: list[Any] = []
        while pos < len(lines):
            row = lines[pos]
            if row.indent != indent or not row.content.startswith("- "):
                break
            item = row.content[2:].strip()
            pos += 1
            if item:
                out.append(_parse_scalar(item))
                continue

            if pos >= len(lines) or lines[pos].indent <= indent:
                out.append({})
                continue

            child, pos = _parse_node(lines, pos, lines[pos].indent)
            out.append(child)
        return out, pos

    out_dict: dict[str, Any] = {}
    while pos < len(lines):
        row = lines[pos]
        if row.indent != indent or row.content.startswith("- "):
            break

        key, sep, remainder = row.content.partition(":")
        if not sep:
            raise ValueError(f"YAML 行缺少冒号: {row.content}")
        field = key.strip()
        value = remainder.strip()
        pos += 1

        if value:
            out_dict[field] = _parse_scalar(value)
            continue

        if pos >= len(lines) or lines[pos].indent <= indent:
            out_dict[field] = {}
            continue

        child, pos = _parse_node(lines, pos, lines[pos].indent)
        out_dict[field] = child

    return out_dict, pos


def _parse_scalar(raw: str) -> Any:
    lowered = raw.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None

    if raw.startswith(("'", '"')) and raw.endswith(("'", '"')) and len(raw) >= 2:
        return raw[1:-1]

    try:
        if any(token in raw for token in (".", "e", "E")):
            return float(raw)
        return int(raw)
    except ValueError:
        return raw
