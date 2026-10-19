"""按平台打开设置窗口：让全部配置都在图形界面里完成，不用手改 YAML。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

from ..controller import SwitchScopeController
from ..settings import Settings


def open_preferences(settings: Settings, controller: SwitchScopeController,
                     config_path: Path, log: Any, autostart_enabled: bool,
                     on_saved: Callable[[Any], None]) -> Any:
    if sys.platform == "darwin":
        from .prefs_mac import PrefsWindow
    elif sys.platform == "win32":
        from .prefs_windows import PrefsWindow
    else:  # pragma: no cover
        raise RuntimeError(f"暂不支持 {sys.platform} 的设置窗口")

    window = PrefsWindow(
        settings, controller, config_path, log, autostart_enabled, on_saved
    )
    window.show()
    return window
