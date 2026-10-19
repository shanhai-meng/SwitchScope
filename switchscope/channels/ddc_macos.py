"""macOS DDC/CI 通道。

两条路，按可用性依次尝试：

1. 内建实现：直接向 IOKit 的 DCPAVServiceProxy 发送 I2C 写（DDC/CI 帧），
   不需要任何外部二进制。Apple Silicon 的外接屏走 USB-C DP Alt Mode 时有效。
2. 回退：调用 Homebrew 的 `m1ddc`（./vendored 亦可），能力相同。

注意：部分 Mac 的内置 HDMI 口不传 DDC/CI，此时两条路都不通，
应改用澎湃 OS 局域网通道（见 hyperos.py）。
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import shutil
import subprocess
import time
from typing import Any

from .base import Channel, SourceInfo, SwitchError

DDC_SLAVE = 0x37          # 7-bit slave address，IIC 层会补成写地址 0x6E
DDC_HOST = 0x51           # host address
DDC_CHECKSUM_SEED = 0x6E  # 校验和从 slave 写地址开始异或
VCP_INPUT_SOURCE = 0x60

# VCP 0x60 常见输入源值；显示器不同固件可能有出入，以实际测试为准
INPUT_PRESETS = {
    1: "VGA",
    3: "DVI",
    15: "DisplayPort 1",
    16: "DisplayPort 2",
    17: "HDMI 1",
    18: "HDMI 2",
    27: "USB-C",
}


def build_frame(opcode: int, value: int) -> bytes:
    """构造 DDC/CI set VCP feature 帧。"""
    payload = bytes(
        [
            DDC_HOST,
            0x80 | 3,
            0x03,  # set VCP feature operation code
            opcode & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ]
    )
    checksum = DDC_CHECKSUM_SEED
    for byte in payload:
        checksum ^= byte
    return payload + bytes([checksum & 0xFF])


def build_get_frame(opcode: int) -> bytes:
    """构造 DDC/CI get VCP feature 请求帧（只读，不改变显示器设置）。"""
    payload = bytes([DDC_HOST, 0x80 | 2, 0x01, opcode & 0xFF])
    checksum = DDC_CHECKSUM_SEED
    for byte in payload:
        checksum ^= byte
    return payload + bytes([checksum & 0xFF])


class IOKitDDC:
    """对 IOKit / CoreFoundation 的轻量 ctypes 封装。"""

    def __init__(self) -> None:
        self.iokit = ctypes.CDLL(
            ctypes.util.find_library("IOKit")
            or "/System/Library/Frameworks/IOKit.framework/IOKit",
            use_errno=True,
        )
        self.corefoundation = ctypes.CDLL(
            ctypes.util.find_library("CoreFoundation")
            or "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
            use_errno=True,
        )
        self._bind()

    def _bind(self) -> None:
        io = self.iokit
        cf = self.corefoundation

        io.IOServiceMatching.restype = ctypes.c_void_p
        io.IOServiceMatching.argtypes = [ctypes.c_char_p]

        io.IOServiceGetMatchingServices.restype = ctypes.c_int
        io.IOServiceGetMatchingServices.argtypes = [
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint),
        ]

        io.IOIteratorNext.restype = ctypes.c_uint
        io.IOIteratorNext.argtypes = [ctypes.c_uint]

        io.IOObjectRelease.restype = ctypes.c_int
        io.IOObjectRelease.argtypes = [ctypes.c_uint]

        io.IOAVServiceCreateWithService.restype = ctypes.c_void_p
        io.IOAVServiceCreateWithService.argtypes = [ctypes.c_void_p, ctypes.c_uint]

        io.IOAVServiceWriteI2C.restype = ctypes.c_int
        io.IOAVServiceWriteI2C.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]

        io.IOAVServiceReadI2C.restype = ctypes.c_int
        io.IOAVServiceReadI2C.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]

        cf.CFRelease.restype = None
        cf.CFRelease.argtypes = [ctypes.c_void_p]

    def av_services(self) -> list[tuple[int, ctypes.c_void_p]]:
        """返回 (service port, IOAVServiceRef) 列表，按总线顺序排列。"""
        matching = self.iokit.IOServiceMatching(b"DCPAVServiceProxy")
        if not matching:
            raise SwitchError("无法构造 DCPAVServiceProxy 匹配字典")
        iterator = ctypes.c_uint(0)
        ret = self.iokit.IOServiceGetMatchingServices(
            0,  # kIOMasterPortDefault
            matching,
            ctypes.byref(iterator),
        )
        if ret != 0:
            raise SwitchError(f"IOServiceGetMatchingServices 失败: {ret}")

        services: list[tuple[int, ctypes.c_void_p]] = []
        try:
            while True:
                candidate = self.iokit.IOIteratorNext(iterator)
                if not candidate:
                    break
                av = self.iokit.IOAVServiceCreateWithService(None, candidate)
                if av:
                    services.append((candidate, av))
                else:
                    self.iokit.IOObjectRelease(candidate)
        finally:
            self.iokit.IOObjectRelease(iterator)
        return services

    def write(self, av: ctypes.c_void_p, opcode: int, value: int) -> None:
        frame = build_frame(opcode, value)
        ret = self.iokit.IOAVServiceWriteI2C(
            av, DDC_SLAVE, DDC_HOST, frame, len(frame)
        )
        if ret != 0:
            raise SwitchError(f"IOAVServiceWriteI2C 失败: {ret}")

    def read(self, av: ctypes.c_void_p, opcode: int) -> tuple[int, int] | None:
        """读取一个 VCP 值，返回 (当前值, 最大值)；读不到返回 None。"""
        request = build_get_frame(opcode)
        ret = self.iokit.IOAVServiceWriteI2C(
            av, DDC_SLAVE, DDC_HOST, request, len(request)
        )
        if ret != 0:
            return None
        time.sleep(0.05)  # DDC/CI 要求两次传输之间留出间隔
        buffer = ctypes.create_string_buffer(11)
        ret = self.iokit.IOAVServiceReadI2C(
            av, DDC_SLAVE, DDC_HOST, buffer, 11
        )
        if ret != 0:
            return None
        reply = bytes(buffer.raw)
        start = None
        for i, byte in enumerate(reply):
            if byte & 0xFE == DDC_CHECKSUM_SEED:  # 0x6E / 0x6F 数据头
                start = i
                break
        if start is None or start + 10 >= len(reply):
            return None
        if reply[start + 1] != 0x88:  # get VCP feature reply 的长度字节
            return None
        maximum = reply[start + 6] << 8 | reply[start + 7]
        current = reply[start + 8] << 8 | reply[start + 9]
        return current, maximum

    def release(self, services: list[tuple[int, ctypes.c_void_p]]) -> None:
        for port, av in services:
            try:
                self.corefoundation.CFRelease(ctypes.c_void_p(av))
            except Exception:  # pragma: no cover
                pass
            try:
                self.iokit.IOObjectRelease(port)
            except Exception:  # pragma: no cover
                pass


class DDCChannel(Channel):
    name = "ddc"

    def __init__(self, settings: Any, log: Any) -> None:
        super().__init__(settings, log)
        self._iokit: IOKitDDC | None = None
        self._m1ddc = shutil.which("m1ddc") or (
            "/opt/homebrew/bin/m1ddc" if os.path.exists("/opt/homebrew/bin/m1ddc") else None
        )

    # ---- 自检 / 能力 ----

    def self_check(self) -> str:
        """真实探活：读一次 VCP，读不通就说明这条路不能用。"""
        services = self._services(refresh=True)
        if not services:
            raise SwitchError(
                "没有找到可写 DDC 的外接显示器"
                "（若走 HDMI 口，Mac 可能不转发 DDC/CI；可换 USB-C/DP 线重试）"
            )
        if self._iokit is None:  # pragma: no cover - 类型收窄
            raise SwitchError("IOKit 未初始化")

        for index, (_, av) in enumerate(services, start=1):
            # 先读输入源（VCP 0x60），读不到再退而读亮度（VCP 0x10）：
            # 两者都是只读操作，不会改变显示器的任何设置
            result = self._iokit.read(av, VCP_INPUT_SOURCE)
            opcode = VCP_INPUT_SOURCE
            if result is None:
                result = self._iokit.read(av, 0x10)
                opcode = 0x10
            if result is None:
                continue
            current, maximum = result
            name = "输入源" if opcode == VCP_INPUT_SOURCE else "亮度"
            return (
                f"DDC/CI 可用（第 {index} 条总线），"
                f"读取到{name}当前值 {current}（上限 {maximum}）"
            )

        raise SwitchError(
            "显示器没有应答 DDC/CI —— 它可能不支持 DDC/CI"
            "（REDMI/小米显示器常见），或 Mac 走的是不转发 DDC 的接口；"
            "请改用澎湃 OS 局域网通道，或换 USB-C/DP 线并打开显示器菜单里的 DDC/CI 开关"
        )

    def list_sources(self) -> list[SourceInfo]:
        return [
            SourceInfo(source_id=k, name=v) for k, v in sorted(INPUT_PRESETS.items())
        ]

    # ---- 内部 ----

    def _services(self, refresh: bool = False) -> list[tuple[int, ctypes.c_void_p]]:
        if refresh:
            self._iokit = None
        if self._iokit is None:
            try:
                self._iokit = IOKitDDC()
            except Exception as exc:  # pragma: no cover - 库缺失
                raise SwitchError(f"IOKit 不可用: {exc}") from exc
        return self._iokit.av_services()

    def _pick(self, services: list[tuple[int, ctypes.c_void_p]]) -> ctypes.c_void_p:
        index = max(1, self.settings.ddc_display_index)
        if index > len(services):
            index = 1
        return services[index - 1][1]

    # ---- 切换 ----

    def switch(self, value: int) -> None:
        if self.settings.ddc_display_index == 0 and self._m1ddc:
            # 显式指定 0 时优先走 m1ddc
            self._switch_via_m1ddc(value)
            return

        services = self._services()
        if not services:
            if self._m1ddc:
                self._switch_via_m1ddc(value)
                return
            raise SwitchError("没有可写 DDC 的外接显示器")

        if self._iokit is None:  # pragma: no cover - 类型收窄
            raise SwitchError("IOKit 未初始化")

        try:
            self._iokit.write(self._pick(services), VCP_INPUT_SOURCE, value)
            time.sleep(0.05)
            self.log.info("已通过 DDC/CI 写入 VCP 0x60 = %s", value)
        except SwitchError as exc:
            if not self._m1ddc or len(services) <= 1:
                raise
            # 第一条总线常常对应内屏，逐个总线再试一次
            for i, (_, av) in enumerate(services[1:], start=2):
                try:
                    self._iokit.write(av, VCP_INPUT_SOURCE, value)
                    self.log.info(
                        "已通过 DDC/CI 第 %s 条总线写入 VCP 0x60 = %s", i, value
                    )
                    return
                except SwitchError:
                    continue
            raise SwitchError(f"DDC/CI 写入失败: {exc}") from exc

    def _switch_via_m1ddc(self, value: int) -> None:
        if not self._m1ddc:
            raise SwitchError("未安装 m1ddc，无法使用该回退通道")
        index = max(1, self.settings.ddc_display_index)
        proc = subprocess.run(
            [self._m1ddc, "display", str(index), "set", "input", str(value)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode != 0:
            raise SwitchError(proc.stderr.strip() or "m1ddc 执行失败")
        self.log.info("已通过 m1ddc 切换到输入源 %s", value)
