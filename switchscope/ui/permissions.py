"""macOS 权限检测与引导。

SwitchScope 在 macOS 上需要三项权限：

1. **辅助功能** —— 用 pynput 监听全局热键（F12）
2. **输入监控** —— 同上，macOS 10.15 起被拆成独立的一项
3. **本地网络** —— 访问局域网里的显示器（例如 192.168.88.128:6095）

前两项缺了，按热键不会有任何反应（菜单栏里点着切仍然可用）；
第三项缺了，会搜不到显示器。首次启动时弹窗引导一次。
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

# 系统设置里对应面板的跳转 URL
URL_ACCESSIBILITY = (
    "x-apple.systempreferences:com.apple.preference.security"
    "?Privacy_Accessibility"
)
URL_INPUT_MONITORING = (
    "x-apple.systempreferences:com.apple.preference.security"
    "?Privacy_ListenEvent"
)
URL_LOCAL_NETWORK = (
    "x-apple.systempreferences:com.apple.preference.security"
    "?Privacy_LocalNetwork"
)

ACCESSIBILITY_URL = URL_ACCESSIBILITY
INPUT_MONITORING_URL = URL_INPUT_MONITORING
LOCAL_NETWORK_URL = URL_LOCAL_NETWORK

PERMISSION_TEXT = (
    "1. 辅助功能 —— 用于监听全局热键（F12）\n"
    "2. 输入监控 —— 同上，macOS 10.15 起单独列出\n"
    "3. 本地网络 —— 用于访问局域网里的显示器\n\n"
    "缺少前两项时，按 F12 不会有任何反应（菜单里点着切仍可用）。\n"
    "缺少第三项时，会搜不到显示器。"
)


def _state_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/SwitchScope"
    return Path.home() / ".switchscope"


def accessibility_trusted() -> bool:
    """是否已获得「辅助功能」授权（检测不了就当已授权，避免骚扰用户）。"""
    if sys.platform != "darwin":
        return True
    try:
        from ApplicationServices import (  # noqa: PLC0415
            AXIsProcessTrustedWithOptions,
        )

        return bool(AXIsProcessTrustedWithOptions({}))
    except Exception:  # pragma: no cover - 老系统或缺少框架
        return True


def open_panel(url: str) -> None:
    """打开系统设置里对应的隐私面板。"""
    if sys.platform == "darwin":
        subprocess.run(["open", url], check=False)
    else:  # pragma: no cover
        subprocess.run(["start", url], shell=True, check=False)


def open_accessibility() -> None:
    open_panel(URL_ACCESSIBILITY)


def open_input_monitoring() -> None:
    open_panel(URL_INPUT_MONITORING)


def open_local_network() -> None:
    open_panel(URL_LOCAL_NETWORK)


def _already_prompted() -> bool:
    return (_state_dir() / "permission_prompted").exists()


def _mark_prompted() -> None:
    try:
        path = _state_dir()
        path.mkdir(parents=True, exist_ok=True)
        (path / "permission_prompted").write_text("1", encoding="utf-8")
    except OSError:  # pragma: no cover
        pass


def show_permission_dialog() -> str:
    """弹出权限说明窗口，返回用户点选：accessibility / input / later。"""
    from AppKit import NSAlert, NSAlertStyleInformational  # noqa: PLC0415

    alert = NSAlert.alloc().init()
    alert.setAlertStyle_(NSAlertStyleInformational)
    alert.setMessageText_("SwitchScope 需要以下权限")
    alert.setInformativeText_(PERMISSION_TEXT)
    alert.addButtonWithTitle_("打开辅助功能设置")
    alert.addButtonWithTitle_("打开输入监控设置")
    alert.addButtonWithTitle_("稍后再说")

    choice = alert.runModal()
    if choice == 1000:  # NSAlertFirstButtonReturn
        open_accessibility()
        return "accessibility"
    if choice == 1001:  # NSAlertSecondButtonReturn
        open_input_monitoring()
        return "input"
    return "later"


def prompt_once(log: logging.Logger | None = None) -> None:
    """首次启动时引导授权；弹过一次之后不再打扰。

    必须在 NSApplication 已经跑起来之后调用（否则模态窗口不显示）。
    """
    if sys.platform != "darwin" or _already_prompted():
        return
    _mark_prompted()
    if accessibility_trusted():
        return
    try:
        result = show_permission_dialog()
        if log:
            log.info("权限引导窗口：用户选择了 %s", result)
    except Exception as exc:  # pragma: no cover
        if log:
            log.warning("权限引导窗口显示失败: %s", exc)
