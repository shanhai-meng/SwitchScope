"""配置模型与加载。

配置文件描述「一台显示器 + 若干台机器」，两台机器各放一份同一份文件：
每台机器只在 `self` 字段上不同，其余一致，便于手工维护。

样例见仓库根目录 config.example.yaml。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_HOTKEY = "<f12>"
DEFAULT_CHANNELS = ("hyperos", "ddc")


class ConfigError(Exception):
    """配置缺失或不合法。"""


@dataclass
class Machine:
    """一台接在显示器某个输入源上的电脑。"""

    key: str
    label: str
    sources: dict[str, int] = field(default_factory=dict)

    def source(self, channel_name: str) -> int | None:
        return self.sources.get(channel_name)

    @property
    def has_any_source(self) -> bool:
        return bool(self.sources)


@dataclass
class Settings:
    self_key: str
    machines: dict[str, Machine]
    hyperos_host: str | None = None
    hyperos_auto_discover: bool = True
    channels: tuple[str, ...] = DEFAULT_CHANNELS
    hotkey: str = DEFAULT_HOTKEY
    timeout: float = 3.0
    ddc_display_index: int = 1
    verbose: bool = False

    @property
    def self_machine(self) -> Machine:
        return self.machines[self.self_key]

    def peer_keys(self) -> list[str]:
        return [k for k in self.machines if k != self.self_key]

    def peer(self, key: str | None = None) -> Machine:
        """返回对端机器；多机器场景下可指定 key。"""
        keys = self.peer_keys()
        if not keys:
            raise ConfigError("配置中只有一台机器，无从切换")
        target = key or keys[0]
        if target not in keys:
            raise ConfigError(f"未知机器: {target}")
        return self.machines[target]


def _parse_machine(key: str, raw: Any) -> Machine:
    if not isinstance(raw, dict):
        raise ConfigError(f"machines.{key} 必须是一个对象")
    label = str(raw.get("label") or key)
    sources: dict[str, int] = {}
    for name in ("hyperos", "ddc"):
        value = raw.get(name)
        if value is None:
            continue
        try:
            sources[name] = int(value)
        except (TypeError, ValueError) as exc:  # pragma: no cover - 配置错误
            raise ConfigError(f"machines.{key}.{name} 必须是整数") from exc
    if not sources:
        raise ConfigError(f"machines.{key} 至少要在 hyperos / ddc 中填一个输入源编号")
    return Machine(key=key, label=label, sources=sources)


def load_settings(path: str | Path) -> Settings:
    p = Path(path).expanduser()
    if not p.exists():
        raise ConfigError(f"配置文件不存在: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError("配置文件内容必须是键值结构")

    machines_raw = data.get("machines") or {}
    if not isinstance(machines_raw, dict) or len(machines_raw) < 2:
        raise ConfigError("machines 至少要定义两台机器")

    machines = {k: _parse_machine(k, v) for k, v in machines_raw.items()}
    self_key = str(data.get("self") or "")
    if self_key not in machines:
        raise ConfigError(
            f"self 必须是 machines 中的一台: {self_key!r} 不在 {sorted(machines)}"
        )

    display = data.get("display") or {}
    if not isinstance(display, dict):
        raise ConfigError("display 必须是键值结构")

    channels = tuple(str(c).strip() for c in (data.get("channels") or DEFAULT_CHANNELS))
    if not channels:
        raise ConfigError("channels 不能为空")

    return Settings(
        self_key=self_key,
        machines=machines,
        hyperos_host=(display.get("hyperos_host") or None) or None,
        hyperos_auto_discover=bool(display.get("auto_discover", True)),
        channels=channels,
        hotkey=str(data.get("hotkey") or DEFAULT_HOTKEY),
        timeout=float(data.get("timeout") or 3.0),
        ddc_display_index=int(display.get("ddc_display_index") or 1),
        verbose=bool(data.get("verbose", False)),
    )


def example_config() -> str:
    """返回带注释的默认配置模板，用于初始化。"""
    return """# SwitchScope 配置：两台机器各放一份，内容一致
#
# 每台机器用不同的 self，其余字段保持一致

self: mac

# 显示器设置
display:
  # REDMI G Pro 27U 等澎湃 OS 显示器的局域网地址
  # 留空则首次启动时扫描局域网自动发现，发现结果会写回本文件
  hyperos_host: ""
  auto_discover: true
  # DDC/CI 通道使用的显示器序号（1 为第一块外接屏）
  ddc_display_index: 1

# 每台机器接在显示器的哪个输入源上
# hyperos: 澎湃 OS 局域网接口里的 sourceId
# ddc:     DDC/CI 里的 VCP 0x60 输入源值（备用通道）
machines:
  mac:
    label: "Mac"
    hyperos: 30      # USB-C
    ddc: 27          # USB-C（VCP 0x60）
  windows:
    label: "Windows"
    hyperos: 23      # HDMI1
    ddc: 17          # HDMI1（VCP 0x60）

# 控制通道优先级，前面的可用就优先用
channels:
  - hyperos
  - ddc

# 全局热键：两台机器建议用同一个键，语义都是「切到另一台」
# 默认 F12：单键即可触发，Mac 和 Windows 通用
# 如需组合键写成 "<ctrl>+<alt>+s"，留空则只保留菜单点击
hotkey: "<f12>"

timeout: 3.0
verbose: false
"""
