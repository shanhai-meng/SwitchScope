"""控制通道抽象。

一条「通道」= 一种能让显示器换输入源的技术路径。
SwitchScope 启动时按配置顺序逐个自检，用第一个真正可用的通道。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class SwitchError(Exception):
    """切换失败。"""

    def __init__(self, message: str, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass
class SourceInfo:
    """一个输入源。"""

    source_id: int
    name: str


class Channel:
    """通道基类：子类实现 `self_check` 与 `switch`。"""

    name = "base"

    def __init__(self, settings: Any, log: Any) -> None:
        self.settings = settings
        self.log = log

    # ---- 子类实现 ----

    def self_check(self) -> str:
        """返回可读的自检描述；不可用应抛 SwitchError。"""
        raise NotImplementedError

    def switch(self, value: int) -> None:
        """把显示器切到给定输入源编号。"""
        raise NotImplementedError

    def list_sources(self) -> list[SourceInfo]:  # 可选
        return []

    # ---- 通用工具 ----

    def _require(self, value: int | None, machine_label: str) -> int:
        if value is None:
            raise SwitchError(
                f"未配置 {machine_label} 在 {self.name} 通道下的输入源编号"
            )
        return value
