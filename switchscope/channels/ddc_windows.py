"""Windows DDC/CI 通道。

Directly 调用系统的 Monitor Configuration API（dxva2.dll）：
    EnumDisplayMonitors -> GetNumberOfPhysicalMonitorsFromHMONITOR
    -> GetPhysicalMonitorsFromHMONITOR -> SetVCPFeature(hMonitor, 0x60, value)

Windows 对 DDC/CI 的支持通常比 macOS 好；若显示器菜单里有 DDC/CI 开关，
需要先打开。
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from typing import Any

from .base import Channel, SourceInfo, SwitchError

VCP_INPUT_SOURCE = 0x60

INPUT_PRESETS = {
    1: "VGA",
    3: "DVI",
    15: "DisplayPort 1",
    16: "DisplayPort 2",
    17: "HDMI 1",
    18: "HDMI 2",
    27: "USB-C",
}


class PHYSICAL_MONITOR(ctypes.Structure):
    _fields_ = [
        ("hPhysicalMonitor", wintypes.HANDLE),
        ("szPhysicalMonitorDescription", wintypes.WCHAR * 128),
    ]


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMONITOR,
    wintypes.HDC,
    ctypes.POINTER(_RECT),
    wintypes.LPARAM,
)


class DDCChannel(Channel):
    name = "ddc"

    def __init__(self, settings: Any, log: Any) -> None:
        super().__init__(settings, log)
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.dxva2 = ctypes.WinDLL("dxva2", use_last_error=True)
        self._bind()

    def _bind(self) -> None:
        self.user32.EnumDisplayMonitors.restype = wintypes.BOOL
        self.user32.EnumDisplayMonitors.argtypes = [
            wintypes.HDC,
            ctypes.POINTER(_RECT),
            MONITORENUMPROC,
            wintypes.LPARAM,
        ]

        self.dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.restype = wintypes.BOOL
        self.dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [
            wintypes.HMONITOR,
            ctypes.POINTER(wintypes.DWORD),
        ]

        self.dxva2.GetPhysicalMonitorsFromHMONITOR.restype = wintypes.BOOL
        self.dxva2.GetPhysicalMonitorsFromHMONITOR.argtypes = [
            wintypes.HMONITOR,
            wintypes.DWORD,
            ctypes.POINTER(PHYSICAL_MONITOR),
        ]

        self.dxva2.SetVCPFeature.restype = wintypes.BOOL
        self.dxva2.SetVCPFeature.argtypes = [
            wintypes.HANDLE,
            ctypes.c_ubyte,
            wintypes.DWORD,
        ]

        self.dxva2.DestroyPhysicalMonitors.restype = wintypes.BOOL
        self.dxva2.DestroyPhysicalMonitors.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(PHYSICAL_MONITOR),
        ]

    # ---- 枚举 ----

    def _logical_monitors(self) -> list[wintypes.HMONITOR]:
        found: list[int] = []

        @MONITORENUMPROC
        def _cb(hmonitor, _hdc, _rect, _lparam):  # type: ignore[no-untyped-def]
            found.append(hmonitor)
            return True

        if not self.user32.EnumDisplayMonitors(None, None, _cb, 0):
            raise SwitchError(
                f"EnumDisplayMonitors 失败: {ctypes.get_last_error()}"
            )
        return found

    def _physical_monitors(self) -> tuple[list[PHYSICAL_MONITOR], list[str]]:
        handles: list[PHYSICAL_MONITOR] = []
        names: list[str] = []
        for logical in self._logical_monitors():
            count = wintypes.DWORD(0)
            if not self.dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(
                logical, ctypes.byref(count)
            ):
                continue
            if count.value == 0:
                continue
            array = (PHYSICAL_MONITOR * count.value)()
            if not self.dxva2.GetPhysicalMonitorsFromHMONITOR(
                logical, count, array
            ):
                continue
            for i in range(count.value):
                handles.append(array[i])
                names.append(array[i].szPhysicalMonitorDescription or f"Monitor {i}")
        if not handles:
            raise SwitchError("没有找到支持 DDC/CI 的物理显示器")
        return handles, names

    def _release(self, handles: list[PHYSICAL_MONITOR]) -> None:
        if not handles:
            return
        array = (PHYSICAL_MONITOR * len(handles))(*handles)
        self.dxva2.DestroyPhysicalMonitors(len(handles), array)

    # ---- 通道接口 ----

    def self_check(self) -> str:
        handles, names = self._physical_monitors()
        desc = "、".join(names)
        self._release(handles)
        if not handles:
            raise SwitchError("没有支持 DDC/CI 的显示器（检查显示器菜单里的 DDC/CI 开关）")
        return f"DDC/CI 可用，物理显示器: {desc}"

    def list_sources(self) -> list[SourceInfo]:
        return [
            SourceInfo(source_id=k, name=v) for k, v in sorted(INPUT_PRESETS.items())
        ]

    def switch(self, value: int) -> None:
        handles, names = self._physical_monitors()
        try:
            index = 0
            if len(handles) > 1:
                index = min(
                    len(handles) - 1, max(0, self.settings.ddc_display_index - 1)
                )
            monitor = handles[index]
            for attempt in range(3):
                if self.dxva2.SetVCPFeature(
                    monitor.hPhysicalMonitor, VCP_INPUT_SOURCE, value
                ):
                    self.log.info(
                        "已通过 DDC/CI 在 %s 上写入 VCP 0x60 = %s",
                        names[index],
                        value,
                    )
                    return
                ctypes.windll.kernel32.Sleep(50)  # type: ignore[attr-defined]
            raise SwitchError(
                f"SetVCPFeature 失败，错误码 {ctypes.get_last_error()}"
            )
        finally:
            self._release(handles)
