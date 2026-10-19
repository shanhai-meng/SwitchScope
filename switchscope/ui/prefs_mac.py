"""macOS 设置窗口：用 AppKit 原生控件实现（不依赖 tkinter）。

不用 tkinter 的原因：它在 macOS 上必须在主线程跑自己的事件循环，
会和菜单栏 App 的 NSApplication 循环打架。
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable

from AppKit import (
    NSAlert,
    NSApp,
    NSBackingStoreBuffered,
    NSButton,
    NSComboBox,
    NSFont,
    NSPanel,
    NSSwitchButton,
    NSTextField,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
import objc
from Foundation import NSMakeRect, NSObject
from PyObjCTools import AppHelper

from ..controller import SwitchScopeController
from ..settings import Settings
from .prefs_common import HOTKEY_PRESETS, PrefsFormValues, list_source_options

WIDTH = 540
LABEL_W = 172
CTRL_X = 196
ROW = 32
PAD = 18


def _label(text: str, x: float, y: float, width: float = LABEL_W,
           bold: bool = False) -> Any:
    view = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, width, 20))
    view.setStringValue_(text)
    view.setBezeled_(False)
    view.setDrawsBackground_(False)
    view.setEditable_(False)
    view.setSelectable_(False)
    if bold:
        view.setFont_(NSFont.boldSystemFontOfSize_(13))
    return view


def _field(value: str, x: float, y: float, width: float = 180) -> Any:
    view = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, width, 22))
    view.setStringValue_(value)
    view.setEditable_(True)
    return view


def _combo(items: list[str], value: str, x: float, y: float,
           width: float = 210) -> Any:
    view = NSComboBox.alloc().initWithFrame_(NSMakeRect(x, y, width, 24))
    view.addItemsWithObjectValues_(items)
    view.setStringValue_(value)
    view.setEditable_(True)
    return view


def _button(title: str, x: float, y: float, width: float = 90) -> Any:
    view = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, width, 28))
    view.setTitle_(title)
    return view


class _Actions(NSObject):
    def initWithTarget_(self, target: Any):
        self = objc.super(_Actions, self).init()
        if self is None:  # pragma: no cover
            return None
        self.target = target
        return self

    def onSave_(self, _sender: Any) -> None:  # noqa: N802 - AppKit selector
        self.target.handle_save()

    def onCancel_(self, _sender: Any) -> None:  # noqa: N802
        self.target.handle_cancel()

    def onSearch_(self, _sender: Any) -> None:  # noqa: N802
        self.target.handle_search()


class PrefsWindow:
    """设置窗口：show() 以模态方式弹出，保存后回调 on_saved(values)。"""

    def __init__(self, settings: Settings, controller: SwitchScopeController,
                 config_path: Path, log: logging.Logger,
                 autostart_enabled: bool,
                 on_saved: Callable[[PrefsFormValues], None]) -> None:
        self.settings = settings
        self.controller = controller
        self.config_path = config_path
        self.log = log
        self.on_saved = on_saved
        self.initial_autostart = autostart_enabled
        self.panel: Any = None
        self.actions: Any = None
        self._control_order: list[tuple[str, str, Any, list[str], list[Any]]] = []
        self.ctrl_self: Any = None
        self.field_host: Any = None
        self.combo_hotkey: Any = None
        self.check_auto: Any = None
        self.button_search: Any = None

    # ---- 构建界面 ----

    def build(self) -> None:
        rows = 6 + len(self.settings.machines) * len(self.settings.channels)
        height = rows * ROW + 74
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, height),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False,
        )
        panel.setTitle_("SwitchScope 设置")
        view = panel.contentView()
        self._control_order = []

        y = height - 40
        identities = [
            f"{machine.label}（{key}）"
            for key, machine in self.settings.machines.items()
        ]
        self.ctrl_self = _combo(
            identities,
            f"{self.settings.self_machine.label}（{self.settings.self_key}）",
            CTRL_X, y,
        )
        view.addSubview_(_label("本机身份", PAD, y + 3))
        view.addSubview_(self.ctrl_self)
        y -= ROW

        self.field_host = _field(self.settings.hyperos_host or "", CTRL_X, y)
        self.button_search = _button("搜索", CTRL_X + 192, y - 3, 66)
        view.addSubview_(_label("显示器地址", PAD, y + 3))
        view.addSubview_(self.field_host)
        view.addSubview_(self.button_search)
        y -= ROW + 4

        view.addSubview_(_label("输入源分配", PAD, y + 2, 200, bold=True))
        y -= ROW

        options = list_source_options(self.controller)
        for key, machine in self.settings.machines.items():
            for channel in self.settings.channels:
                pairs = options.get(channel) or []
                current = machine.source(channel)
                values = [value for _text, value in pairs]
                if pairs:
                    labels = [text for text, _value in pairs]
                    text = ""
                    if current is not None:
                        text = (
                            labels[values.index(current)]
                            if current in values
                            else str(current)
                        )
                    control: Any = _combo(labels, text, CTRL_X, y)
                else:
                    # 通道给不出源列表（例如 DDC/CI 不可用），退化为手填编号
                    labels = []
                    control = _field(
                        "" if current is None else str(current), CTRL_X, y, 120
                    )
                # ObjC 控件不允许挂自定义属性，所以选项直接随元组一路带到保存时
                view.addSubview_(
                    _label(f"{machine.label} · {channel}", PAD, y + 3, LABEL_W)
                )
                view.addSubview_(control)
                self._control_order.append(
                    (key, channel, control, labels, values)
                )
                y -= ROW

        self.combo_hotkey = _combo(HOTKEY_PRESETS, self.settings.hotkey,
                                   CTRL_X, y)
        view.addSubview_(_label("热键", PAD, y + 3))
        view.addSubview_(self.combo_hotkey)
        y -= ROW

        self.check_auto = NSButton.alloc().initWithFrame_(
            NSMakeRect(PAD, y, 240, 22)
        )
        self.check_auto.setButtonType_(NSSwitchButton)
        self.check_auto.setTitle_("开机自动启动")
        self.check_auto.setState_(1 if self.initial_autostart else 0)
        view.addSubview_(self.check_auto)
        y -= ROW + 8

        cancel = _button("取消", WIDTH - 190, y)
        save = _button("保存", WIDTH - 95, y)
        self.actions = _Actions.alloc().initWithTarget_(self)
        save.setTarget_(self.actions)
        save.setAction_("onSave:")
        cancel.setTarget_(self.actions)
        cancel.setAction_("onCancel:")
        self.button_search.setTarget_(self.actions)
        self.button_search.setAction_("onSearch:")
        view.addSubview_(cancel)
        view.addSubview_(save)

        self.panel = panel

    # ---- 交互 ----

    def show(self) -> None:
        if self.panel is None:
            self.build()
        NSApp.runModalForWindow_(self.panel)

    def handle_cancel(self) -> None:
        self.panel.orderOut_(None)
        NSApp.stopModal()

    def handle_save(self) -> None:
        from .prefs_common import save as persist
        from .prefs_common import validate_hotkey

        values = self.collect()
        error = validate_hotkey(values.hotkey)
        if error:
            self._alert(error)
            return
        try:
            persist(self.config_path, values, self.log)
        except Exception as exc:
            self._alert(str(exc))
            return
        self.panel.orderOut_(None)
        NSApp.stopModal()
        self.on_saved(values)

    def handle_search(self) -> None:
        self.button_search.setTitle_("搜索中…")
        self.button_search.setEnabled_(False)

        def work() -> None:
            try:
                from ..channels import create_channel

                channel = create_channel("hyperos", self.settings, self.log)
                host = channel.discover()
            except Exception as exc:
                AppHelper.callAfter(self._search_done, None, exc)
                return
            AppHelper.callAfter(self._search_done, host, None)

        threading.Thread(target=work, daemon=True).start()

    def _search_done(self, host: str | None, error: Exception | None) -> None:
        self.button_search.setTitle_("搜索")
        self.button_search.setEnabled_(True)
        if error or not host:
            self._alert(f"没有搜到显示器：{error or '未知原因'}")
            return
        self.field_host.setStringValue_(host)
        self.settings.hyperos_host = host
        self.controller.reset_channel()

    def collect(self) -> PrefsFormValues:
        values = PrefsFormValues(
            self_key=self.settings.self_key,
            host=str(self.field_host.stringValue()),
            hotkey=str(self.combo_hotkey.stringValue()),
            autostart=bool(self.check_auto.state()),
        )
        chosen = str(self.ctrl_self.stringValue()).strip()
        for key, machine in self.settings.machines.items():
            if chosen in (key, f"{machine.label}（{key}）"):
                values.self_key = key
                break
        for key in self.settings.machines:
            values.sources[key] = {}
        for item in self._control_order:
            machine_key, channel_name, control, labels, option_values = item
            text = str(control.stringValue()).strip()
            if not text:
                values.sources[machine_key][channel_name] = ""
                continue
            # 先看是不是下拉里选的某项（按文字反查编号），再退回手输的数字
            if text in labels:
                values.sources[machine_key][channel_name] = option_values[
                    labels.index(text)
                ]
                continue
            try:
                values.sources[machine_key][channel_name] = int(text)
            except ValueError:
                values.sources[machine_key][channel_name] = text
        return values

    def _alert(self, message: str) -> None:
        alert = NSAlert.alloc().init()
        alert.setMessageText_("SwitchScope")
        alert.setInformativeText_(message)
        alert.runModal()
