"""小米澎湃 OS（HyperOS）显示器局域网遥控通道。

REDMI 显示器 G Pro 27U 等型号不支持 DDC/CI，但开机后在局域网的
6095 端口提供一个遥控 HTTP 接口：

    GET /request?action=isalive        -> data.devicename
    GET /controller?action=getsources  -> data.sourceList[{sourceId, sourceName}]
    GET /controller?action=changesource2&sourceid=N

响应信封统一为 {"msg": "success", "data": {...}}。

这条通道的优势：与视频线无关，Mac / Windows / Linux 只要能连到同一个
局域网，就能把显示器切到任意输入源。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..discover import scan_port
from .base import Channel, SourceInfo, SwitchError

PORT = 6095

# 显示器专属输入源编号（MStar 固件沿用电视定义：29 = DP，30 = USB-C）
SOURCE_DP = 29
SOURCE_USBC = 30


def _name_overrides(source_id: int) -> str | None:
    return {SOURCE_DP: "DP", SOURCE_USBC: "USB-C"}.get(source_id)


class HyperOSChannel(Channel):
    name = "hyperos"

    def __init__(self, settings: Any, log: Any) -> None:
        super().__init__(settings, log)
        self.host: str | None = settings.hyperos_host or None
        self._sources: list[SourceInfo] | None = None
        self._device_name: str | None = None

    # ---- 请求层 ----

    def _call(self, path: str, params: dict[str, str], timeout: float | None = None
              ) -> dict[str, Any]:
        if not self.host:
            raise SwitchError("尚未确定显示器地址", transient=True)
        url = f"http://{self.host}:{PORT}/{path}?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(
                url, timeout=timeout or self.settings.timeout
            ) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise SwitchError(f"显示器无响应: {exc}", transient=True) from exc
        if payload.get("msg") != "success":
            raise SwitchError(f"显示器拒绝了请求: {payload.get('msg')!r}")
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    # ---- 发现 ----

    def discover(self) -> str:
        """扫描局域网寻找澎湃 OS 显示器，返回 IP。找不到抛 SwitchError。"""
        self.log.info("开始扫描局域网寻找澎湃 OS 显示器…")
        live = scan_port(PORT, timeout=0.45)
        self.log.debug("开放 %s 的主机: %s", PORT, live)
        for host in live:
            probe = HyperOSChannel(self.settings, self.log)
            probe.host = host
            try:
                name = probe.device_name()
                sources = probe.sources()
            except SwitchError:
                continue
            if _looks_like_monitor(name, sources):
                self.log.info("发现显示器 %s (%s)", name, host)
                self.host = host
                self._device_name = name
                self._sources = sources
                return host
        raise SwitchError("局域网内没有找到澎湃 OS 显示器", transient=True)

    def _ensure_host(self, discover: bool) -> str:
        if self.host:
            return self.host
        if not (discover and self.settings.hyperos_auto_discover):
            raise SwitchError("未配置显示器地址且未开启自动发现")
        return self.discover()

    # ---- 能力 ----

    def device_name(self) -> str:
        if self._device_name:
            return self._device_name
        data = self._call("request", {"action": "isalive"})
        name = str(data.get("devicename") or "未知设备")
        self._device_name = name
        return name

    def sources(self) -> list[SourceInfo]:
        if self._sources is not None:
            return self._sources
        data = self._call("controller", {"action": "getsources"})
        result: list[SourceInfo] = []
        for item in data.get("sourceList") or []:
            try:
                sid = int(item.get("sourceId"))
            except (TypeError, ValueError):
                continue
            name = _name_overrides(sid) or str(item.get("sourceName") or f"源 {sid}")
            result.append(SourceInfo(source_id=sid, name=name))
        self._sources = result
        return result

    def probe_current_source(self) -> int | None:
        """尽力读取当前信号源编号；固件不支持时返回 None。"""
        for action in ("getsource", "getcurrentsource", "getcurrentsrc"):
            try:
                data = self._call(
                    "controller", {"action": action}, timeout=1.2
                )
            except SwitchError:
                continue
            for key in ("sourceId", "sourceid", "source", "currentsource"):
                value = data.get(key)
                if isinstance(value, int):
                    return value
        return None

    # ---- 通道接口 ----

    def self_check(self) -> str:
        self._ensure_host(discover=True)
        name = self.device_name()
        try:
            sources = self.sources()
        except SwitchError:
            sources = []
        desc = "、".join(f"{s.name}={s.source_id}" for s in sources) or "输入源未知"
        return f"{name}（{self.host}）— 可选输入源: {desc}"

    def list_sources(self) -> list[SourceInfo]:
        self._ensure_host(discover=True)
        return self.sources()

    def switch(self, value: int) -> None:
        self._ensure_host(discover=True)
        known = {s.source_id for s in self.sources()}
        if known and value not in known:
            names = "、".join(s.name for s in self.sources())
            raise SwitchError(f"输入源编号 {value} 不在显示器支持的范围（{names}）")
        self._call(
            "controller", {"action": "changesource2", "sourceid": str(value)}
        )
        self.log.info("已通过澎湃 OS 接口切换到输入源 %s", value)


def _looks_like_monitor(name: str, sources: list[SourceInfo]) -> bool:
    """把显示器和其他同接口的电视区分开（避免误切客厅电视）。"""
    lowered = name.lower()
    if "显示器" in name or "monitor" in lowered:
        return True
    return any(s.source_id in (SOURCE_DP, SOURCE_USBC) for s in sources)
