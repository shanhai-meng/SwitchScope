"""在保留注释与排版的前提下，改写 YAML 配置里的某个字段。

设置窗口保存时需要改好几个字段；如果用 yaml.safe_dump 重写整个文件，
用户辛苦写下的中文注释会被冲掉，所以这里做行级定位替换。
"""
from __future__ import annotations

import re

_KEY_LINE = re.compile(r"^(?P<ind>\s*)(?P<key>[A-Za-z0-9_\-]+)\s*:(?P<rest>.*)$")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _is_content(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def format_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return '"' + str(value).replace('"', '\\"') + '"'


def _child_block(lines: list[str], start: int, end: int, parent_indent: int
                 ) -> tuple[int, int | None]:
    """计算第 start 行的子块范围，返回 (结束行, 子块缩进)。"""
    index = start + 1
    child_indent: int | None = None
    while index < end:
        line = lines[index]
        if _is_content(line):
            indent = _indent(line)
            if indent <= parent_indent:
                break
            if child_indent is None:
                child_indent = indent
        index += 1
    return index, child_indent


def _patch_block(lines: list[str], start: int, end: int, indent: int,
                 path: list[str], value: object) -> bool:
    index = start
    while index < end:
        line = lines[index]
        if not _is_content(line):
            index += 1
            continue
        current = _indent(line)
        if current < indent:  # 已经越过当前块，没必要再找
            return False
        if current == indent:
            match = _KEY_LINE.match(line)
            if match and match.group("key") == path[0]:
                if len(path) == 1:
                    newline = "\n" if line.endswith("\n") else ""
                    lines[index] = (
                        f"{match.group('ind')}{match.group('key')}:"
                        f" {format_value(value)}{newline}"
                    )
                    return True
                stop, child_indent = _child_block(lines, index, end, indent)
                if child_indent is None:
                    return False
                return _patch_block(lines, index + 1, stop, child_indent,
                                    path[1:], value)
            # 不是目标 key：连同它的子块一起跳过
            stop, _ = _child_block(lines, index, end, indent)
            index = max(stop, index + 1)
            continue
        index += 1
    return False


def patch_scalar(text: str, path: list[str], value: object) -> tuple[str, bool]:
    """把 text 里 path 指向的标量改成 value，返回 (新文本, 是否改到)。"""
    lines = text.splitlines(keepends=True)
    if not _patch_block(lines, 0, len(lines), 0, list(path), value):
        return text, False
    return "".join(lines), True


def patch_all(text: str, changes: list[tuple[list[str], object]]) -> str:
    """连续应用多组改动；找不到的键原样保留，避免破坏文件。"""
    for path, value in changes:
        text, _ok = patch_scalar(text, path, value)
    return text
