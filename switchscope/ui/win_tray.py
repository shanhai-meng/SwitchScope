"""Windows 托盘 App（pystray + Pillow）。

功能与 macOS 菜单栏版一致：托盘菜单列出对端机器、通道状态与诊断。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from .. import __version__
from ..autostart import is_enabled as is_autostart_enabled
from ..autostart import set_autostart
from ..controller import SwitchScopeController
from ..settings import Settings
from .hotkey import HotKey, available, hotkey_label

_APP_NAME = "SwitchScope"

# 开机自启时网络可能还没就绪，通道检测失败要重试几次再下结论
RETRY_TIMES = 4
RETRY_INTERVAL = 4


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
        self._update_info: dict[str, str] | None = None
        threading.Thread(target=self._check_update_async, daemon=True).start()

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
        items.append(
            pystray.MenuItem(
                "开机自启",
                self.on_toggle_autostart,
                checked=lambda item: is_autostart_enabled(),
            )
        )
        items.append(pystray.MenuItem("设置…", self.on_prefs))
        items.append(pystray.MenuItem("打开配置文件", self.on_open_config))
        items.append(pystray.Menu.SEPARATOR)
        if self._update_info:
            items.append(
                pystray.MenuItem(
                    f"有新版本 v{self._update_info['version']}（点击下载）",
                    self.on_open_update,
                )
            )
        items.append(
            pystray.MenuItem(f"关于 SwitchScope v{__version__}", self.on_about)
        )
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
        """通道检测：开机自启时网络可能还没就绪，失败就重试几次。"""
        desc = "未知状态"
        for attempt in range(RETRY_TIMES):
            try:
                self.controller.active_channel(refresh=True)
                desc = self.controller.channel_description
                break
            except Exception as exc:  # pragma: no cover
                desc = f"不可用：{exc}"
                if attempt < RETRY_TIMES - 1:
                    time.sleep(RETRY_INTERVAL)
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

    # ---- 版本更新 ----

    def _check_update_async(self) -> None:
        """启动后查一下有没有新版本；查到就在菜单里插入提示项。"""
        from .update_check import check_latest  # noqa: PLC0415

        time.sleep(6)  # 等启动完成，也避免刚联网那几秒失败
        info = check_latest()
        if not info:
            return
        self._update_info = info
        if self.icon:
            self.icon.menu = self.build_menu()
            self.icon.update_menu()
        self.notify(f"SwitchScope v{info['version']} 已发布，点托盘菜单下载")

    def on_open_update(self, _icon=None, _item=None) -> None:
        import webbrowser  # noqa: PLC0415

        url = (self._update_info or {}).get(
            "url", "https://github.com/shanhai-meng/SwitchScope/releases/latest"
        )
        webbrowser.open(url)

    def on_about(self, _icon=None, _item=None) -> None:
        """显示版本、本机身份、显示器地址等一览信息。"""
        import tkinter.messagebox as messagebox

        host = self.settings.hyperos_host or "（未设置，可在『设置…』里搜索）"
        messagebox.showinfo(
            f"关于 SwitchScope v{__version__}",
            "\n".join([
                f"本机身份：{self.settings.self_machine.label}"
                f"（{self.settings.self_key}）",
                f"热键：{hotkey_label(self.settings.hotkey, 'default')}",
                f"显示器：{host}",
                "",
                f"配置文件：{self.config_path}",
            ]),
        )

    def on_prefs(self, _icon=None, _item=None) -> None:
        from ..settings import load_settings
        from .settings_window import open_preferences

        def on_saved(_values: object) -> None:
            try:
                new_settings = load_settings(self.config_path)
            except Exception as exc:
                self.notify(f"配置有误：{exc}")
                return
            self.apply_settings(new_settings)
            self.notify("设置已保存，热键与输入源分配已生效")

        open_preferences(
            self.settings, self.controller, self.config_path, self.log,
            is_autostart_enabled(), on_saved,
        )

    def apply_settings(self, settings: Settings) -> None:
        self.settings = settings
        self.controller.settings = settings
        self.controller.reset_channel()
        try:
            self.hotkey.stop()
        except Exception:  # pragma: no cover
            pass
        self.hotkey = HotKey(settings.hotkey, self.on_hotkey, self.log)
        try:
            self.hotkey.start()
        except Exception as exc:  # pragma: no cover
            self.log.warning("全局热键重注册失败: %s", exc)
        if self.icon:
            self.icon.menu = self.build_menu()

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
