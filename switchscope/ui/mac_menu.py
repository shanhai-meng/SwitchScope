"""macOS 菜单栏 App（rumps）。

标题显示本机标识，菜单里列出对端机器、当前通道状态与诊断入口。
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path

import rumps

from ..autostart import is_enabled as is_autostart_enabled
from ..autostart import set_autostart
from ..controller import SwitchScopeController
from ..settings import Settings
from .hotkey import HotKey, available, hotkey_label

SEPARATOR = None

ACCESSIBILITY_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"


def accessibility_trusted() -> bool:
    """是否已获得辅助功能权限（全局热键的前提）。无法判断时按「已授权」处理。"""
    try:
        from ApplicationServices import AXIsProcessTrusted  # 延迟导入

        return bool(AXIsProcessTrusted())
    except Exception:  # pragma: no cover - 非 macOS 或 API 变更
        return True


class MenuApp(rumps.App):
    def __init__(self, settings: Settings, controller: SwitchScopeController,
                 config_path: Path, logger: logging.Logger) -> None:
        super().__init__(
            name="SwitchScope",
            title=f"🖥 {settings.self_machine.label}",
            quit_button=None,
        )
        self.settings = settings
        self.controller = controller
        self.config_path = config_path
        self.log = logger
        self._busy = threading.Lock()

        self.peer_items: dict[str, rumps.MenuItem] = {}
        for key, machine in settings.machines.items():
            if key == settings.self_key:
                continue
            item = rumps.MenuItem(f"切到 {machine.label}", callback=self.on_switch)
            item._target_key = key  # type: ignore[attr-defined]
            self.peer_items[key] = item

        self.item_self = rumps.MenuItem(
            f"切回本机（{settings.self_machine.label}）", callback=self.on_switch_self
        )
        self.item_status = rumps.MenuItem("检测通道…", callback=None)
        self.item_redetect = rumps.MenuItem("重新检测通道", callback=self.on_redetect)
        self.item_probe = rumps.MenuItem("诊断信息…", callback=self.on_probe)
        self.item_config = rumps.MenuItem("打开配置文件", callback=self.on_open_config)
        self.item_log = rumps.MenuItem("打开日志目录", callback=self.on_open_log)
        self.item_autostart = rumps.MenuItem(
            "开机自启", callback=self.on_toggle_autostart
        )
        self.item_autostart.state = is_autostart_enabled()
        self.item_quit = rumps.MenuItem("退出", callback=self.on_quit)
        self.item_prefs = rumps.MenuItem("设置…", callback=self.on_prefs)

        self._build_menu()

        self.hotkey = HotKey(settings.hotkey, self.on_hotkey, logger)
        self._start_hotkey()

    def _build_menu(self) -> None:
        """按当前配置重建菜单（换本机身份 / 改机器名 / 改热键后刷新）。"""
        label = hotkey_label(self.settings.hotkey, "darwin")
        self.peer_items = {
            key: self.peer_items.get(key) or rumps.MenuItem(
                "", callback=self.on_switch
            )
            for key, machine in self.settings.machines.items()
            if key != self.settings.self_key
        }
        for key, item in self.peer_items.items():
            item.title = f"切到 {self.settings.machines[key].label}  {label}"
            item._target_key = key  # type: ignore[attr-defined]
            item.set_callback(self.on_switch)

        self.item_self.title = f"切回本机（{self.settings.self_machine.label}）"
        self.title = f"🖥 {self.settings.self_machine.label}"

        self.menu = [
            *self.peer_items.values(),
            self.item_self,
            SEPARATOR,
            self.item_status,
            self.item_redetect,
            self.item_probe,
            SEPARATOR,
            self.item_prefs,
            self.item_autostart,
            self.item_config,
            self.item_log,
            SEPARATOR,
            self.item_quit,
        ]

    # ---- 启动 ----

    def _start_hotkey(self) -> None:
        error = available()
        if error:
            self.notify("热键未启用", f"pynput 不可用：{error}")
            return
        if not accessibility_trusted():
            self.item_accessibility = rumps.MenuItem(
                "授权全局热键…", callback=self.on_open_accessibility
            )
            self.menu.insert_after("重新检测通道", self.item_accessibility)
            self.notify(
                "还差一步：授权辅助功能",
                "点击菜单栏里新增的「授权全局热键…」，勾上本程序后重启即可用快捷键",
            )
        try:
            self.hotkey.start()
        except Exception as exc:
            self.log.warning("全局热键注册失败: %s", exc)
            self.notify("热键注册失败", str(exc))
        else:
            label = hotkey_label(self.settings.hotkey, "darwin")
            if self.peer_items:
                first = next(iter(self.peer_items.values()))
                first.title = f"{first.title}  {label}"

    @rumps.timer(1.0)
    def refresh_status(self, _sender=None) -> None:
        """后台刷新一次通道状态（首次显示后不再轮询，避免打扰显示器）。"""
        if self.item_status.title != "检测通道…":
            return
        threading.Thread(target=self._detect_async, daemon=True).start()

    def _detect_async(self) -> None:
        try:
            desc = self.controller.channel_description
        except Exception as exc:  # pragma: no cover
            desc = f"通道不可用：{exc}"
        self.item_status.title = f"通道: {desc}"

    # ---- 交互 ----

    def on_hotkey(self) -> None:
        try:
            message = self.controller.toggle()
        except Exception as exc:
            self.notify("切换失败", str(exc))
            self.log.exception("热键切换失败")
            return
        self.notify("SwitchScope", message)

    def on_switch(self, sender) -> None:
        key = getattr(sender, "_target_key", None)
        self.do_switch(key)

    def on_switch_self(self, _sender=None) -> None:
        self.do_switch(self.settings.self_key)

    def do_switch(self, key: str | None) -> None:
        if not self._busy.acquire(blocking=False):
            self.notify("请稍候", "上一次切换还在进行")
            return
        try:
            message = self.controller.switch_to(key or self.settings.peer().key)
        except Exception as exc:
            self.log.exception("切换失败")
            self.notify("切换失败", str(exc))
        else:
            self.notify("SwitchScope", message)
        finally:
            self._busy.release()

    def on_redetect(self, _sender=None) -> None:
        self.controller.reset_channel()
        self.item_status.title = "检测通道…"

    def on_open_accessibility(self, _sender=None) -> None:
        subprocess.run(["open", ACCESSIBILITY_URL], check=False)
        self.notify(
            "打开隐私设置",
            "在「辅助功能」列表里勾选 Python / SwitchScope，再退出本程序重新启动",
        )

    def on_probe(self, _sender=None) -> None:
        try:
            report = self.controller.diagnostics()
        except Exception as exc:  # pragma: no cover
            report = f"诊断失败: {exc}"
        rumps.Window(
            message=report, title="SwitchScope 诊断", dimensions=(640, 380),
            ok="好", cancel=None,
        ).run()

    def on_open_config(self, _sender=None) -> None:
        subprocess.run(["open", "-t", str(self.config_path)], check=False)

    def on_open_log(self, _sender=None) -> None:
        log_dir = Path.home() / "Library/Application Support/SwitchScope/logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(log_dir)], check=False)

    def on_prefs(self, _sender=None) -> None:
        """打开设置窗口：所有改动保存后立即生效。"""
        from ..settings import load_settings
        from .settings_window import open_preferences

        def on_saved(_values: object) -> None:
            try:
                new_settings = load_settings(self.config_path)
            except Exception as exc:
                self.notify("配置有误", str(exc))
                return
            self.apply_settings(new_settings)
            self.notify("设置已保存", "热键与输入源分配已立即生效")

        open_preferences(
            self.settings, self.controller, self.config_path, self.log,
            is_autostart_enabled(), on_saved,
        )

    def apply_settings(self, settings: Settings) -> None:
        """用新配置刷新：控制器、热键、菜单一起换过来。"""
        self.settings = settings
        self.controller.settings = settings
        self.controller.reset_channel()
        self.item_status.title = "检测通道…"
        self.item_autostart.state = is_autostart_enabled()
        try:
            self.hotkey.stop()
        except Exception:  # pragma: no cover
            pass
        self.hotkey = HotKey(settings.hotkey, self.on_hotkey, self.log)
        try:
            self.hotkey.start()
        except Exception as exc:
            self.log.warning("全局热键重注册失败: %s", exc)
        self._build_menu()

    def on_toggle_autostart(self, sender=None) -> None:
        wanted = not is_autostart_enabled()
        try:
            set_autostart(wanted, sys.argv[0], self.config_path)
        except Exception as exc:
            self.notify("开机自启设置失败", str(exc))
            return
        if sender is not None:
            sender.state = wanted
        self.notify(
            "开机自启已开启" if wanted else "开机自启已关闭",
            "下次开机自动出现在菜单栏" if wanted else "不再随系统启动",
        )

    def on_quit(self, _sender=None) -> None:
        self.hotkey.stop()
        rumps.quit_application()

    def notify(self, title: str, message: str) -> None:
        try:
            rumps.notification(
                title="SwitchScope", subtitle=title, message=message, sound=False
            )
        except Exception:  # pragma: no cover
            pass


def run(settings: Settings, controller: SwitchScopeController,
        config_path: Path, logger: logging.Logger) -> None:
    MenuApp(settings, controller, config_path, logger).run()
