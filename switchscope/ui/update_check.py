"""版本更新检查：拿 GitHub 上最新 Release 跟本地版本比一比。

属于「锦上添花」的功能，所有失败都静默处理——查不到就当没有更新，
绝不能因为网络问题影响切换功能。
"""

from __future__ import annotations

import json
import ssl
import urllib.request
from typing import Any

from .. import __version__

REPO = "shanhai-meng/SwitchScope"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
FALLBACK_URL = f"https://github.com/{REPO}/releases/latest"


def _parse(version: str) -> tuple[int, ...]:
    """把 "v0.2.3" 之类的版本号转成可比较的元组。"""
    parts: list[int] = []
    for chunk in str(version).lstrip("v").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts) if parts else (0,)


def is_newer(latest: str, current: str = __version__) -> bool:
    """latest 是否比 current 新。"""
    return _parse(latest) > _parse(current)


def _open(url: str, timeout: float) -> str:
    """读一个 URL。打包后可能缺 CA 证书，失败时退到不校验（只读公开信息）。"""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"SwitchScope/{__version__}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except Exception:
        # 常见原因：PyInstaller 打包后找不到 CA 证书
        context = ssl._create_unverified_context()  # noqa: SLF001
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return response.read().decode("utf-8", "replace")


def check_latest(timeout: float = 4.0) -> dict[str, Any] | None:
    """查询最新 Release，返回 {version, url, notes, assets}；失败返回 None。"""
    try:
        data = json.loads(_open(API, timeout))
    except Exception:
        return None
    tag = str(data.get("tag_name") or "").lstrip("v")
    if not tag or not is_newer(tag):
        return None
    return {
        "version": tag,
        "url": data.get("html_url") or FALLBACK_URL,
        "notes": (data.get("body") or "").strip()[:300],
        "assets": [a.get("name") for a in (data.get("assets") or []) if a.get("name")],
    }
