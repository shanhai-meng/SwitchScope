"""设置窗口的平台无关部分：取值整理、写回配置、热重载。

平台相关的表单实现在 prefs_mac.py（AppKit）与 prefs_windows.py（Tkinter）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..controller import SwitchScopeController
from ..settings import Settings, load_settings
from .config_editor import patch_all
from .hotkey import parse_hotkey

# 热键预设：给不想手输的人直接选
HOTKEY_PRESETS = [
    "<f12>", "<f11>", "<f10>", "<f9>", "<f8>",
    "<ctrl>+<alt>+s", "<ctrl>+<alt>+k", "<cmd>+<shift>+x",
    "<ctrl>+<shift>+s", "",
]


@dataclass
class PrefsFormValues:
    """设置窗口里收集到的全部取值。"""

    self_key: str = ""
    host: str = ""
    hotkey: str = ""
    autostart: bool = False
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    # 形如 {"mac": {"hyperos": 30, "ddc": 27}}


def list_source_options(controller: SwitchScopeController) -> dict[str, list[tuple[str, Any]]]:
    """按通道取可用输入源列表，返回 {通道名: [(显示文字, 值), ...]}。"""
    options: dict[str, list[tuple[str, Any]]] = {}
    for name in controller.settings.channels:
        options[name] = []
        try:
            channel = _make_channel(controller, name)
            for info in channel.list_sources():
                options[name].append((f"{info.name}  （编号 {info.source_id}）",
                                      info.source_id))
        except Exception:  # pragma: no cover - 通道不可用就给空列表
            continue
    return options


def _make_channel(controller: SwitchScopeController, name: str):
    from ..channels import create_channel

    return create_channel(name, controller.settings, controller.log)


def validate_hotkey(hotkey: str) -> str | None:
    """返回错误说明；合法则返回 None。空串表示「不注册热键」。"""
    if not hotkey.strip():
        return None
    if parse_hotkey(hotkey) is None:
        return (
            f"热键 {hotkey!r} 无法识别。可用写法：<f12>、<ctrl>+<alt>+s、<cmd>+<shift>+x"
        )
    return None


def build_changes(values: PrefsFormValues) -> list[tuple[list[str], object]]:
    """把窗口取值转换成配置文件的字段改动。"""
    changes: list[tuple[list[str], object]] = []
    if values.self_key:
        changes.append((["self"], values.self_key))
    changes.append((["display", "hyperos_host"], values.host.strip()))
    changes.append((["hotkey"], values.hotkey.strip()))
    for machine_key, per_channel in values.sources.items():
        for channel_name, value in per_channel.items():
            if value is None or value == "":
                continue
            changes.append((["machines", machine_key, channel_name], value))
    return changes


def save(config_path: Path, values: PrefsFormValues,
         log: logging.Logger | None = None) -> None:
    """保存：写入配置文件 + 同步开机自启。"""
    text = config_path.read_text(encoding="utf-8")
    text = patch_all(text, build_changes(values))
    config_path.write_text(text, encoding="utf-8")
    if log:
        log.info("设置已保存: %s", config_path)

    try:
        from ..autostart import set_autostart

        set_autostart(values.autostart, None, config_path)
    except Exception as exc:  # pragma: no cover
        if log:
            log.exception("开机自启设置失败")
        raise RuntimeError(f"开机自启设置失败：{exc}") from exc


def reload_settings(config_path: Path) -> Settings:
    return load_settings(config_path)
