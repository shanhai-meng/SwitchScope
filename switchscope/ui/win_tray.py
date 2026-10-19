"""Windows 托盘 App（pystray + Pillow）。

功能与 macOS 菜单栏版一致：托盘菜单列出对端机器、通道状态与诊断。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

from ..autostart import is_enabled as is_autostart_enabled
from ..autostart import set_autostart
from ..controller import SwitchScopeController
from ..settings import Settings
from .hotkey import HotKey, available, hotkey_label

_APP_NAME = "SwitchScope"


def _icon_image():
    """画一个显示器形状作为托盘图标。"""
    from PIL import Image, ImageDraw  # 延迟导入：macOS 端不需要 Pillow

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([6, 12, 58, 44], radius=6, fill=(34, 38, 46, 255))
    draw.rounded_rectangle([10, 16, 54, 40], radius=3, fill=(64, 180, 255, 255))
    draw.rectangle([26, 46, 38, 52], fill=(90, 96, 106, 255))
    draw.rectangle([16, 52, 48, 57], fill=(90, 96, 106, 255))
    return img


class TrayApp:
    def __init__(self, settings: Settings, controller: SwitchScopeController,
                 config_path: Path, logger: logging.Logger) -> None:
        self.settings = settings
        self.controller = controller
        self.config_path = config_path
        self.log = logger
        self._busy = threading.Lock()
        self.hotkey = HotKey(settings.hotkey, self.on_hotkey, logger)
        self.icon = None

    # ---- 菜单 ----

    def build_menu(self):
        import pystray

        items = []
        label = hotkey_label(self.settings.hotkey, "default")
        for key, machine in self.settings.machines.items():
            if key == self.settings.self_key:
                continue
            items.append(
                pystray.MenuItem(
                    f"切到 {machine.label}  {label}",
                    lambda icon, item, key=key: self.do_switch(key),
                )
            )
        items.append(
            pystray.MenuItem(
                f"切回本机（{self.settings.self_machine.label}）",
                lambda icon, item: self.do_switch(self.settings.self_key),
            )
        )
        items.append(pystray.Menu.SEPARATOR)
        items.append(
            pystray.MenuItem("通道状态", self.on_status, enabled=False)
        )
        items.append(pystray.MenuItem("重新检测通道", self.on_redetect))
        items.append(pystray.MenuItem("诊断信息（写到桌面）", self.on_probe))
        items.append(pystray.MenuItem("打开配置文件", self.on_open_config))
        items.append(
            pystray.MenuItem(
                "开机自启",
                self.on_toggle_autostart,
                checked=lambda item: is_autostart_enabled(),
            )
        )
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("退出", self.on_quit))
        return pystray.Menu(*items)

    # ---- 行为 ----

    def on_hotkey(self) -> None:
        try:
            message = self.controller.toggle()
        except Exception as exc:
            self.log.exception("热键切换失败")
            self.notify(f"切换失败：{exc}")
            return
        self.notify(message)

    def do_switch(self, key: str) -> None:
        if not self._busy.acquire(blocking=False):
            self.notify("上一次切换还在进行")
            return
        try:
            message = self.controller.switch_to(key)
        except Exception as exc:
            self.log.exception("切换失败")
            self.notify(f"切换失败：{exc}")
        else:
            self.notify(message)
        finally:
            self._busy.release()

    def on_status(self, _icon=None, _item=None) -> None:
        pass

    def on_redetect(self, _icon=None, _item=None) -> None:
        self.controller.reset_channel()
        threading.Thread(target=self._refresh, daemon=True).start()

    def _refresh(self) -> None:
        try:
            desc = self.controller.channel_description
        except Exception as exc:  # pragma: no cover
            desc = f"通道不可用：{exc}"
        title = f"{_APP_NAME} - {self.settings.self_machine.label}"
        if self.icon is not None:
            self.icon.title = title
            self.icon.notify(f"当前通道: {desc}")

    def on_probe(self, _icon=None, _item=None) -> None:
        report = self.controller.diagnostics()
        out = Path.home() / "Desktop" / "SwitchScope-诊断.txt"
        out.write_text(report, encoding="utf-8")
        subprocess.Popen(["notepad", str(out)])  # noqa: S603,S607

    def on_open_config(self, _icon=None, _item=None) -> None:
        os.startfile(str(self.config_path))  # type: ignore[attr-defined]  # noqa: S606

    def on_toggle_autostart(self, _icon=None, _item=None) -> None:
        wanted = not is_autostart_enabled()
        try:
            set_autostart(wanted, sys.argv[0], self.config_path)
        except Exception as exc:  # pragma: no cover
            self.log.exception("开机自启设置失败")
            self.notify(f"开机自启设置失败：{exc}")
            return
        self.notify("开机自启已开启" if wanted else "开机自启已关闭")

    def on_quit(self, _icon=None, _item=None) -> None:
        self.hotkey.stop()
        if self.icon is not None:
            self.icon.stop()

    def notify(self, message: str) -> None:
        try:
            if self.icon is not None:
                self.icon.notify(message, _APP_NAME)
        except Exception:  # pragma: no cover
            pass

    # ---- 入口 ----

    def run(self) -> None:
        import pystray

        self.icon = pystray.Icon(
            _APP_NAME,
            _icon_image(),
            f"{_APP_NAME} - {self.settings.self_machine.label}",
            self.build_menu(),
        )
        error = available()
        if error:
            self.log.warning("pynput 不可用: %s", error)
        else:
            try:
                self.hotkey.start()
            except Exception as exc:  # pragma: no cover
                self.log.warning("全局热键注册失败: %s", exc)

        threading.Thread(target=self._refresh, daemon=True).start()
        self.icon.run()


def run(settings: Settings, controller: SwitchScopeController,
        config_path: Path, logger: logging.Logger) -> None:
    TrayApp(settings, controller, config_path, logger).run()
