"""跨平台全局热键（pynput）。

两台机器建议配同一个组合键，语义统一为「切到另一台」：
只有当前使用者正在用的那台会收到按键，天然不会冲突。
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

_KEY_ALIAS = {
    "<cmd>": "cmd", "<command>": "cmd", "<meta>": "cmd", "<win>": "cmd",
    "<shift>": "shift",
    "<ctrl>": "ctrl", "<control>": "ctrl",
    "<option>": "alt", "<alt>": "alt",
}

_MODIFIER_ALIAS = {
    "ctrl_l": "ctrl", "ctrl_r": "ctrl", "ctrl": "ctrl", "control": "ctrl",
    "shift_l": "shift", "shift_r": "shift", "shift": "shift",
    "alt_l": "alt", "alt_r": "alt", "alt": "alt", "alt_gr": "alt", "altgr": "alt",
    "cmd_l": "cmd", "cmd_r": "cmd", "cmd": "cmd", "super_l": "cmd", "super_r": "cmd",
}

_GLYPH = {
    "cmd": {"darwin": "⌘", "default": "Win"},
    "shift": {"darwin": "⇧", "default": "Shift"},
    "ctrl": {"darwin": "⌃", "default": "Ctrl"},
    "alt": {"darwin": "⌥", "default": "Alt"},
}


def parse_hotkey(hotkey: str) -> list[str] | None:
    """'<ctrl>+<alt>+s' -> ['ctrl', 'alt', 's']；单键 '<f12>' -> ['f12']。

    支持单键：F12 这类独立功能键本身就适合用于「一键切屏」。
    无法解析返回 None。
    """
    if not hotkey:
        return None
    parts = [p.strip() for p in hotkey.replace("+", " ").split() if p.strip()]
    if not parts:
        return None
    keys: list[str] = []
    for part in parts:
        inner = part[1:-1] if part.startswith("<") and part.endswith(">") else part
        low = inner.lower()
        canonical = _KEY_ALIAS.get(low) or _MODIFIER_ALIAS.get(low)
        if canonical:
            keys.append(canonical)
        elif len(inner) == 1 and inner.isalnum():
            keys.append(low)
        elif low in {
            "space", "enter", "tab", "esc", "backspace", "delete",
            "up", "down", "left", "right", "f1", "f2", "f3", "f4", "f5",
            "f6", "f7", "f8", "f9", "f10", "f11", "f12", "home", "end",
            "page_up", "page_down",
        }:
            keys.append(low)
        else:
            return None
    return keys


def hotkey_label(hotkey: str, platform: str = "default") -> str:
    keys = parse_hotkey(hotkey)
    if not keys:
        return hotkey or ""
    out: list[str] = []
    for key in keys:
        if key in _GLYPH:
            out.append(_GLYPH[key].get(platform) or _GLYPH[key]["default"])
        elif len(key) == 1:
            out.append(key.upper())
        else:
            out.append(key.replace("_", " ").title())
    sep = "" if platform == "darwin" else "+"
    return sep.join(out)


class HotKey:
    """注册一个全局组合键，触发时回调（回调在监听线程）。"""

    def __init__(self, hotkey: str, callback: Callable[[], None],
                 logger=None) -> None:
        self.hotkey = hotkey
        self.callback = callback
        self.log = logger
        self._listener = None
        self._pressed: set[str] = set()
        self._fired = False
        self._lock = threading.Lock()

    @property
    def combos(self) -> set[str]:
        parsed = parse_hotkey(self.hotkey)
        if not parsed:
            raise ValueError(f"无法解析热键: {self.hotkey!r}")
        return set(parsed)

    def start(self) -> None:
        from pynput import keyboard  # 延迟导入：无需热键时不强依赖

        combos = self.combos

        def _norm(key) -> str | None:
            name = getattr(key, "name", None)
            if name:
                return _MODIFIER_ALIAS.get(name, name)
            char = getattr(key, "char", None)
            return char.lower() if char else None

        def on_press(key):
            name = _norm(key)
            if name is None:
                return
            with self._lock:
                self._pressed.add(name)
                if combos.issubset(self._pressed):
                    if self._fired:
                        return
                    self._fired = True
                else:
                    return
            if self.log:
                self.log.info("全局热键触发: %s", self.hotkey)
            try:
                self.callback()
            except Exception:  # pragma: no cover
                if self.log:
                    self.log.exception("热键回调异常")

        def on_release(key):
            name = _norm(key)
            if name is None:
                return
            with self._lock:
                self._pressed.discard(name)
                if not combos.issubset(self._pressed):
                    self._fired = False

        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._listener.daemon = True
        self._listener.start()
        if self.log:
            self.log.info("全局热键已注册: %s", self.hotkey)

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:  # pragma: no cover
                pass
            self._listener = None


def available() -> Optional[str]:
    """pynput 是否可用，返回错误信息（可用时 None）。"""
    try:
        import pynput  # noqa: F401
        return None
    except Exception as exc:  # pragma: no cover
        return str(exc)
