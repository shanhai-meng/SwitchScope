"""切换控制器：挑选可用通道、执行切换、给出诊断信息。

两台机器运行同一份代码、同一份配置，语义统一为：

- 热键 = 「切到另一台」（toggle）
- 菜单 / CLI = 显式切到某台机器
"""
from __future__ import annotations

import logging
from typing import Any

from .channels import create_channel
from .channels.base import Channel, SwitchError
from .settings import Settings


class SwitchScopeController:
    def __init__(self, settings: Settings, log: logging.Logger | None = None) -> None:
        self.settings = settings
        self.log = log or logging.getLogger("switchscope")
        self._channel: Channel | None = None
        self._description: str = ""
        self.last_error: str | None = None

    # ---- 通道选择 ----

    def active_channel(self, refresh: bool = False) -> Channel:
        if self._channel is not None and not refresh:
            return self._channel

        tried: list[str] = []
        for name in self.settings.channels:
            try:
                channel = create_channel(name, self.settings, self.log)
                desc = channel.self_check()
            except SwitchError as exc:
                tried.append(f"{name}: {exc}")
                self.log.info("通道 %s 不可用: %s", name, exc)
                continue
            except Exception as exc:  # pragma: no cover - 意外错误
                tried.append(f"{name}: {exc}")
                self.log.exception("通道 %s 自检异常", name)
                continue
            self._channel = channel
            self._description = desc
            self.last_error = None
            return channel

        self._channel = None
        self.last_error = "；".join(tried) or "没有可用通道"
        raise SwitchError(f"所有通道都不可用 — {self.last_error}")

    @property
    def channel_name(self) -> str:
        try:
            return self.active_channel().name
        except SwitchError:
            return "不可用"

    @property
    def channel_description(self) -> str:
        try:
            self.active_channel()
        except SwitchError:
            return self.last_error or "不可用"
        return self._description

    def reset_channel(self) -> None:
        self._channel = None
        self._description = ""

    # ---- 切换 ----

    def switch_to(self, machine_key: str) -> str:
        """切到指定机器接的输入源。返回可读结果。"""
        machine = self.settings.machines.get(machine_key)
        if machine is None:
            raise SwitchError(f"未知机器: {machine_key}")

        errors: list[str] = []
        for name in self.settings.channels:
            value = machine.source(name)
            if value is None:
                continue
            try:
                channel = create_channel(name, self.settings, self.log)
                channel.switch(value)
            except SwitchError as exc:
                errors.append(f"{name}: {exc}")
                self.log.info("通道 %s 切换失败: %s", name, exc)
                continue
            self.last_error = None
            self.reset_channel()
            return f"已切到 {machine.label}（{channel.name} → 输入源 {value}）"

        raise SwitchError(
            f"切到 {machine.label} 失败 — {'；'.join(errors) or '没有可用通道'}"
        )

    def switch_self(self) -> str:
        return self.switch_to(self.settings.self_key)

    def toggle(self) -> str:
        """切到另一台机器（默认第一台非本机机器）。"""
        return self.switch_to(self.settings.peer().key)

    # ---- 诊断 ----

    def diagnostics(self) -> str:
        lines = [
            f"本机身份: {self.settings.self_machine.label} ({self.settings.self_key})",
            f"热键: {self.settings.hotkey}",
            f"通道优先级: {' → '.join(self.settings.channels)}",
            "",
        ]
        for name in self.settings.channels:
            try:
                channel = create_channel(name, self.settings, self.log)
                desc = channel.self_check()
                lines.append(f"  [可用] {name}: {desc}")
                sources = channel.list_sources()
                if sources:
                    listing = "、".join(
                        f"{s.name}={s.source_id}" for s in sources
                    )
                    lines.append(f"         输入源: {listing}")
            except SwitchError as exc:
                lines.append(f"  [不可用] {name}: {exc}")
            except Exception as exc:  # pragma: no cover
                lines.append(f"  [异常] {name}: {exc}")

        lines.append("")
        for key, machine in self.settings.machines.items():
            marker = " ← 本机" if key == self.settings.self_key else ""
            source_desc = "、".join(
                f"{name}={value}" for name, value in machine.sources.items()
            )
            lines.append(f"  {machine.label}（{key}）: {source_desc}{marker}")
        return "\n".join(lines)
