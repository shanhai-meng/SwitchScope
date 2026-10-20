"""切换控制器：挑选可用通道、执行切换、给出诊断信息。

两台机器运行同一份代码、同一份配置，语义统一为：

- 热键 = 「切到另一台」（toggle）
- 菜单 / CLI = 显式切到某台机器
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from .channels import create_channel
from .channels.base import Channel, SwitchError
from .settings import Settings


def _state_file() -> Path:
    """记住「上次切到谁」的状态文件（显示器固件查不了当前输入源）。"""
    if sys.platform == "darwin":
        base = Path.home() / "Library/Application Support/SwitchScope"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home())) / "SwitchScope"
    else:
        base = Path.home() / ".switchscope"
    return base / "state.json"


class SwitchScopeController:
    def __init__(self, settings: Settings, log: logging.Logger | None = None) -> None:
        self.settings = settings
        self.log = log or logging.getLogger("switchscope")
        self._channel: Channel | None = None
        self._description: str = ""
        self.last_error: str | None = None
        self._last_target: str | None = self._load_last_target()

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
            self.log.info("通道 %s 就绪: %s", name, desc)
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
        """热键语义：把画面切到对方那台。

        不记忆"上次切到了谁"——键鼠连哪台、F12 就把那台显示器切到对面：
        Mac 端按 → 切到 Windows；Windows 端按 → 切到 Mac。
        这样按一次就能去对面，不会出现来回切的混淆。
        """
        return self.switch_to(self.settings.peer().key)

    # ---- 切换状态记忆 ----

    def _load_last_target(self) -> str | None:
        try:
            data = json.loads(_state_file().read_text(encoding="utf-8"))
            return data.get("last_target")
        except Exception:  # pragma: no cover - 没有状态文件就当没切过
            return None

    def _remember(self, machine_key: str) -> None:
        self._last_target = machine_key
        try:
            path = _state_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"last_target": machine_key}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:  # pragma: no cover
            self.log.warning("保存切换状态失败: %s", exc)

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
