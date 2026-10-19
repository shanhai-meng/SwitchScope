"""通道工厂：按平台挑出可用的控制通道。"""
from __future__ import annotations

import sys
from typing import Any

from .base import Channel, SourceInfo, SwitchError  # noqa: F401
from .hyperos import HyperOSChannel

if sys.platform == "darwin":
    from .ddc_macos import DDCChannel  # type: ignore[assignment]
elif sys.platform == "win32":
    from .ddc_windows import DDCChannel  # type: ignore[assignment]
else:  # Linux 等其他平台暂不支持 DDC 直写
    DDCChannel = None  # type: ignore[assignment]

_FACTORIES: dict[str, Any] = {"hyperos": HyperOSChannel}
if DDCChannel is not None:
    _FACTORIES["ddc"] = DDCChannel


def create_channel(name: str, settings: Any, log: Any) -> Channel:
    factory = _FACTORIES.get(name)
    if factory is None:
        raise SwitchError(f"当前平台不支持通道: {name}")
    return factory(settings, log)


def supported_channels() -> list[str]:
    return list(_FACTORIES)


__all__ = [
    "Channel",
    "SourceInfo",
    "SwitchError",
    "HyperOSChannel",
    "DDCChannel",
    "create_channel",
    "supported_channels",
]
