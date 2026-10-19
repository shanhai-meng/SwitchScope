"""开机自启：macOS LaunchAgent / Windows 启动目录。

成品 App 与源码运行都支持：
- 成品 App（PyInstaller）直接登记可执行文件本身
- 源码运行则登记「虚拟环境内的 python + main.py」
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

LABEL = "com.switchscope.app"


def resolve_interpreter() -> Path:
    """虚拟环境里要用 venv 自身的 python，否则自启时会找不到依赖。"""
    if sys.prefix != sys.base_prefix:  # 运行在虚拟环境中
        for candidate in (
            Path(sys.prefix) / "bin" / "python",
            Path(sys.prefix) / "bin" / "python3",
            Path(sys.prefix) / "Scripts" / "python.exe",
        ):
            if candidate.exists():
                return candidate
    return Path(sys.executable).resolve()


def command_argv(script: str | Path | None, config_path: Path) -> list[str]:
    """构造自启时执行的命令行。"""
    if getattr(sys, "frozen", False):  # 打包后的成品 App
        return [sys.executable, "--config", str(config_path)]
    python = str(resolve_interpreter())
    return [python, str(script), "--config", str(config_path)]


def _plist(argv: list[str]) -> str:
    args = "\n".join(f"        <string>{part}</string>" for part in argv)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{args}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{Path.home()}/Library/Logs/switchscope.log</string>
    <key>StandardErrorPath</key>
    <string>{Path.home()}/Library/Logs/switchscope.log</string>
</dict>
</plist>
"""


def mac_launch_agent(enable: bool, argv: list[str]) -> None:
    agent_dir = Path.home() / "Library/LaunchAgents"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (Path.home() / "Library/Logs").mkdir(parents=True, exist_ok=True)
    plist = agent_dir / f"{LABEL}.plist"
    domain = f"gui/{os.getuid()}"   # bootstrap 接收「域」
    service = f"{domain}/{LABEL}"   # bootout / kickstart 接收「域/服务」

    subprocess.run(
        ["launchctl", "bootout", service], check=False, capture_output=True
    )
    if not enable:
        if plist.exists():
            plist.unlink()
        return

    plist.write_text(_plist(argv), encoding="utf-8")
    result = subprocess.run(
        ["launchctl", "bootstrap", domain, str(plist)],
        check=False, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"launchctl bootstrap 失败: {(result.stderr or '').strip()}"
        )


def windows_startup(enable: bool, argv: list[str]) -> None:
    startup = Path(
        os.environ.get("APPDATA") or str(Path.home() / "AppData/Roaming")
    ) / "Microsoft/Windows/Start Menu/Programs/Startup"
    startup.mkdir(parents=True, exist_ok=True)
    bat = startup / "SwitchScope.bat"

    if not enable:
        if bat.exists():
            bat.unlink()
        return

    raw = argv[0]
    # 源码运行时优先用 pythonw.exe，避免弹出控制台窗口
    if raw.endswith(("python.exe", "python")):
        headless = Path(raw).with_name("pythonw.exe")
        if headless.exists():
            argv = [str(headless), *argv[1:]]
    quoted = " ".join(f'"{part}"' for part in argv)
    bat.write_text("@echo off\r\n" f'start "" {quoted}\r\n', encoding="utf-8")


def is_enabled() -> bool:
    """当前是否已设置开机自启。"""
    if sys.platform == "darwin":
        return (Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist").exists()
    if sys.platform == "win32":
        startup = Path(
            os.environ.get("APPDATA") or str(Path.home() / "AppData/Roaming")
        ) / "Microsoft/Windows/Start Menu/Programs/Startup/SwitchScope.bat"
        return startup.exists()
    return False


def set_autostart(enable: bool, script: str | Path | None, config_path: Path) -> None:
    """按平台写入 / 清除开机自启。"""
    argv = command_argv(script, config_path)
    if sys.platform == "darwin":
        mac_launch_agent(enable, argv)
    elif sys.platform == "win32":
        windows_startup(enable, argv)
    else:
        raise RuntimeError(f"暂不支持 {sys.platform} 的开机自启")
