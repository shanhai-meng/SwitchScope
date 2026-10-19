"""SwitchScope 入口。

用法：
    python main.py                 启动菜单栏 / 托盘（ MacOS / Windows）
    python main.py --probe         打印通道诊断信息
    python main.py --discover      扫描局域网寻找澎湃 OS 显示器并写回配置
    python main.py --toggle        立即切到另一台机器
    python main.py --to windows    立即切到指定机器
    python main.py --autostart on  写入开机自启（Mac: LaunchAgent / Win: 启动目录）
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

APP = "SwitchScope"


def bundle_root() -> Path:
    """模板文件所在目录：PyInstaller 打包后指向解包临时目录，否则是源码根目录。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent


def user_config_path() -> Path:
    """用户级配置目录：成品 App 只读得到 bundle，配置必须放在外面。"""
    if sys.platform == "darwin":
        base = Path.home() / "Library/Application Support" / APP
    elif sys.platform == "win32":
        base = (
            Path(os.environ.get("APPDATA") or str(Path.home() / "AppData/Roaming")) / APP
        )
    else:
        base = Path.home() / ".config" / APP
    return base / "config.yaml"


def default_config_path() -> Path:
    path = user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    legacy = Path(__file__).resolve().parent / "config.yaml"
    if not path.exists() and legacy.exists():
        try:  # 早期版本把配置放在源码目录，迁移过来
            path.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:  # pragma: no cover
            pass
    return path


def ensure_config(path: Path) -> Path:
    if path.exists():
        return path
    template = bundle_root() / "config.example.yaml"
    if template.exists():
        path.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    else:  # pragma: no cover
        from switchscope.settings import example_config

        path.write_text(example_config(), encoding="utf-8")
    print(f"已生成默认配置：{path}")
    print("请先编辑其中的 self 与各台机器的输入源编号，再重新启动。")
    return path


def write_back_host(path: Path, host: str) -> bool:
    """把自动发现到的显示器地址写回配置文件（保留注释）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    pattern = re.compile(
        r'(?m)^(\s*hyperos_host:\s*)("[^"]*"|\'[^\']*\'|\S*)'
    )
    new_text, count = pattern.subn(lambda m: f'{m.group(1)}"{host}"', text, count=1)
    if not count or new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="switchscope",
        description="ScreenSwitch：单显示器下 Mac ↔ Windows 快速切换（与信号源切换等价）",
    )
    parser.add_argument("--config", type=Path, default=None, help="配置文件路径")
    parser.add_argument("--probe", action="store_true", help="打印通道诊断信息并退出")
    parser.add_argument("--discover", action="store_true", help="扫描局域网寻找显示器")
    parser.add_argument("--to", metavar="MACHINE", help="切到指定机器后退出")
    parser.add_argument("--toggle", action="store_true", help="切到另一台机器后退出")
    parser.add_argument(
        "--try", dest="try_source", metavar="VALUE",
        help="试切到某个输入源编号（用于确认各机器插在哪个口）",
    )
    parser.add_argument("--no-hotkey", action="store_true", help="不注册全局热键")
    parser.add_argument(
        "--autostart", choices=("on", "off"), help="配置开机自启"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    return parser


def handle_autostart(mode: str, config_path: Path) -> int:
    from switchscope.autostart import set_autostart

    script = str(Path(__file__).resolve())
    try:
        set_autostart(mode == "on", script, config_path)
    except Exception as exc:
        print(f"设置开机自启失败：{exc}")
        return 1
    print(f"开机自启已{'开启' if mode == 'on' else '关闭'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认可能是 cp936/cp1252，直接输出中文会抛 UnicodeEncodeError
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # pragma: no cover
            pass
    args = build_parser().parse_args(argv)
    config_path = args.config or default_config_path()
    ensure_config(config_path)

    try:
        from switchscope.settings import ConfigError, load_settings

        settings = load_settings(config_path)
    except ConfigError as exc:
        print(f"配置错误：{exc}")
        return 2

    from switchscope.logging_setup import setup_logging

    log = setup_logging(verbose=args.verbose or settings.verbose)

    from switchscope.controller import SwitchScopeController

    controller = SwitchScopeController(settings, log)

    if args.autostart:
        return handle_autostart(args.autostart, config_path)

    if args.probe:
        print(controller.diagnostics())
        return 0

    if args.discover:
        from switchscope.channels import create_channel

        channel = create_channel("hyperos", settings, log)
        try:
            host = channel.discover()
        except Exception as exc:
            print(f"未找到显示器：{exc}")
            return 1
        print(f"找到显示器: {channel.device_name()} ({host})")
        print("输入源编号:", ", ".join(
            f"{s.name}={s.source_id}" for s in channel.sources()
        ))
        if write_back_host(config_path, host):
            print(f"已写入配置文件: {config_path}")
        return 0

    if args.try_source is not None:
        try:
            value = int(args.try_source)
        except ValueError:
            print("输入源编号必须是整数")
            return 1
        try:
            channel = controller.active_channel()
            channel.switch(value)
        except Exception as exc:
            print(f"试切失败：{exc}")
            return 1
        print(f"已请求切到输入源 {value}（{controller.channel_name} 通道）")
        print("看看屏幕是否切到了 Windows / 另一台机器，据此把编号填进配置里。")
        return 0

    if args.to or args.toggle:
        try:
            message = controller.switch_to(args.to) if args.to else controller.toggle()
        except Exception as exc:
            print(f"切换失败：{exc}")
            return 1
        print(message)
        return 0

    # 配置里没填地址时后台自动发现，不阻塞界面启动
    # （万一没赶在首次切换前完成，按热键时也会按需再发现一次）
    if "hyperos" in settings.channels and not settings.hyperos_host:
        import threading

        def _auto_discover() -> None:
            from switchscope.channels import create_channel

            try:
                channel = create_channel("hyperos", settings, log)
                host = channel.discover()
            except Exception:
                return
            if write_back_host(config_path, host):
                log.info("已自动写入显示器地址 %s", host)
            settings.hyperos_host = host
            controller.reset_channel()

        threading.Thread(target=_auto_discover, daemon=True).start()

    try:
        if sys.platform == "darwin":
            from switchscope.ui.mac_menu import run
        elif sys.platform == "win32":
            from switchscope.ui.win_tray import run
        else:
            print(f"暂不支持 {sys.platform} 的图形界面，可用 --probe / --toggle 命令行操作")
            return 1
    except ImportError as exc:
        print(f"界面依赖缺失：{exc}")
        return 1

    if args.no_hotkey:
        settings.hotkey = ""

    run(settings, controller, config_path, log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
