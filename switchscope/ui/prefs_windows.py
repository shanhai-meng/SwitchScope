"""Windows 设置窗口：Tkinter 表单。

窗口在自己的线程里跑 mainloop，避免阻塞托盘的消息循环。
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable

from ..controller import SwitchScopeController
from ..settings import Settings
from .prefs_common import HOTKEY_PRESETS, PrefsFormValues, list_source_options


class PrefsWindow:
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
        self.root: Any = None
        self.rows: list[tuple[str, str, Any, list[Any]]] = []

    # ---- 入口 ----

    def show(self) -> None:
        if self.root is not None:
            return
        threading.Thread(target=self._run, daemon=True).start()

    # ---- 表单 ----

    def _run(self) -> None:
        import tkinter as tk
        from tkinter import messagebox, ttk

        root = tk.Tk()
        self.root = root
        root.title("SwitchScope 设置")
        root.resizable(False, False)
        root.attributes("-topmost", True)
        frame = ttk.Frame(root, padding=14)
        frame.grid(row=0, column=0)

        row = 0
        ttk.Label(frame, text="本机身份").grid(row=row, column=0, sticky="w", pady=6)
        identities = [
            f"{machine.label}（{key}）"
            for key, machine in self.settings.machines.items()
        ]
        var_self = tk.StringVar(
            value=f"{self.settings.self_machine.label}（{self.settings.self_key}）"
        )
        combo_self = ttk.Combobox(frame, textvariable=var_self,
                                  values=identities, state="readonly", width=22)
        combo_self.grid(row=row, column=1, sticky="w")
        row += 1

        ttk.Label(frame, text="显示器地址").grid(row=row, column=0, sticky="w", pady=6)
        var_host = tk.StringVar(value=self.settings.hyperos_host or "")
        entry_host = ttk.Entry(frame, textvariable=var_host, width=24)
        entry_host.grid(row=row, column=1, sticky="w")
        search = ttk.Button(frame, text="搜索", width=8)
        search.grid(row=row, column=2, padx=6)
        row += 1

        ttk.Separator(frame).grid(row=row, column=0, columnspan=3,
                                  sticky="ew", pady=8)
        row += 1
        ttk.Label(frame, text="输入源分配").grid(row=row, column=0,
                                                columnspan=3, sticky="w")
        row += 1

        options = list_source_options(self.controller)
        self.rows = []
        for key, machine in self.settings.machines.items():
            for channel in self.settings.channels:
                pairs = options.get(channel) or []
                labels = [text for text, _value in pairs]
                values = [value for _text, value in pairs]
                current = machine.source(channel)
                text = ""
                if current is not None:
                    text = (
                        labels[values.index(current)]
                        if current in values
                        else str(current)
                    )
                var = tk.StringVar(value=text)
                ttk.Label(frame, text=f"{machine.label} · {channel}").grid(
                    row=row, column=0, sticky="w", pady=4
                )
                if pairs:
                    control = ttk.Combobox(frame, textvariable=var,
                                           values=labels, state="readonly",
                                           width=22)
                else:
                    control = ttk.Entry(frame, textvariable=var, width=24)
                control.grid(row=row, column=1, sticky="w")
                self.rows.append((key, channel, var, labels, values))
                row += 1

        ttk.Label(frame, text="热键").grid(row=row, column=0, sticky="w", pady=6)
        var_hotkey = tk.StringVar(value=self.settings.hotkey)
        ttk.Combobox(frame, textvariable=var_hotkey, values=HOTKEY_PRESETS,
                     width=22).grid(row=row, column=1, sticky="w")
        row += 1

        var_auto = tk.BooleanVar(value=self.initial_autostart)
        ttk.Checkbutton(frame, text="开机自动启动",
                        variable=var_auto).grid(row=row, column=0,
                                                columnspan=2, sticky="w", pady=6)
        row += 1

        ttk.Separator(frame).grid(row=row, column=0, columnspan=3,
                                  sticky="ew", pady=6)
        row += 1

        def on_save() -> None:
            values = self._collect(var_self, var_host, var_hotkey, var_auto)
            from .prefs_common import save as persist
            from .prefs_common import validate_hotkey

            error = validate_hotkey(values.hotkey)
            if error:
                messagebox.showerror("SwitchScope", error)
                return
            try:
                persist(self.config_path, values, self.log)
            except Exception as exc:
                messagebox.showerror("SwitchScope", str(exc))
                return
            root.destroy()
            self.root = None
            self.on_saved(values)

        def on_search() -> None:
            search.configure(state="disabled", text="搜索中")

            def work() -> None:
                try:
                    from ..channels import create_channel

                    channel = create_channel("hyperos", self.settings, self.log)
                    host = channel.discover()
                except Exception as exc:
                    root.after(0, lambda: _search_done(None, exc))
                    return
                root.after(0, lambda: _search_done(host, None))

            def _search_done(host: str | None, error: Exception | None) -> None:
                search.configure(state="normal", text="搜索")
                if error or not host:
                    messagebox.showerror("SwitchScope",
                                         f"没有搜到显示器：{error or '未知原因'}")
                    return
                var_host.set(host)
                self.settings.hyperos_host = host
                self.controller.reset_channel()

            threading.Thread(target=work, daemon=True).start()

        search.configure(command=on_search)

        buttons = ttk.Frame(frame)
        buttons.grid(row=row, column=0, columnspan=3, sticky="e", pady=6)
        ttk.Button(buttons, text="取消", command=lambda: self._close(root)
                   ).grid(row=0, column=0, padx=6)
        ttk.Button(buttons, text="保存", command=on_save).grid(row=0, column=1)

        root.protocol("WM_DELETE_WINDOW", lambda: self._close(root))
        root.mainloop()

    def _close(self, root: Any) -> None:
        root.destroy()
        self.root = None

    def _collect(self, var_self, var_host, var_hotkey,
                 var_auto) -> PrefsFormValues:
        values = PrefsFormValues(
            self_key=self.settings.self_key,
            host=var_host.get(),
            hotkey=var_hotkey.get(),
            autostart=bool(var_auto.get()),
        )
        chosen = var_self.get().strip()
        for key, machine in self.settings.machines.items():
            if chosen in (key, f"{machine.label}（{key}）"):
                values.self_key = key
                break
        for key in self.settings.machines:
            values.sources[key] = {}
        for key, channel, var, labels, option_values in self.rows:
            text = var.get().strip()
            if not text:
                values.sources[key][channel] = ""
            elif text in labels:
                values.sources[key][channel] = option_values[labels.index(text)]
            else:
                try:
                    values.sources[key][channel] = int(text)
                except ValueError:
                    values.sources[key][channel] = text
        return values
