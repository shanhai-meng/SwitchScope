"""生成应用图标并调用 PyInstaller 打包。

    python build_app.py            # 打当前平台
    python build_app.py --skip-icon

产物：
    macOS    -> dist/SwitchScope.app
    Windows  -> dist/SwitchScope.exe
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = "SwitchScope"

COMMON_HIDDEN = [
    "switchscope.ui.hotkey",
    "switchscope.ui.settings_window",
    "switchscope.ui.prefs_common",
    "switchscope.ui.config_editor",
    "switchscope.channels.hyperos",
    "switchscope.autostart",
]

# 设置窗口按平台动态导入，PyInstaller 静态分析抓不到，必须显式声明
MACOS_HIDDEN = [
    "switchscope.ui.prefs_mac",
    "PyObjCTools.AppHelper",
    "objc",
]
WINDOWS_HIDDEN = [
    "switchscope.ui.prefs_windows",
    "tkinter",
    "tkinter.ttk",
    "tkinter.messagebox",
]


def _draw_icon(size: int):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size / 64
    draw.rounded_rectangle([6 * s, 12 * s, 58 * s, 44 * s], radius=6 * s,
                           fill=(34, 38, 46, 255))
    draw.rounded_rectangle([10 * s, 16 * s, 54 * s, 40 * s], radius=3 * s,
                           fill=(64, 180, 255, 255))
    draw.rectangle([26 * s, 46 * s, 38 * s, 52 * s], fill=(90, 96, 106, 255))
    draw.rectangle([16 * s, 52 * s, 48 * s, 57 * s], fill=(90, 96, 106, 255))
    return img


def build_macos_icon() -> list[str]:
    iconset = ROOT / "build" / "iconset.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True, exist_ok=True)
    sizes = [
        (16, "16x16"), (32, "16x16@2x"), (32, "32x32"), (64, "32x32@2x"),
        (128, "128x128"), (256, "128x128@2x"), (256, "256x256"),
        (512, "256x256@2x"), (512, "512x512"), (1024, "512x512@2x"),
    ]
    for px, name in sizes:
        _draw_icon(px).save(iconset / f"icon_{name}.png")
    icns = ROOT / "build" / f"{APP}.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)],
                   check=True)
    return ["--icon", str(icns)]


def build_windows_icon() -> list[str]:
    png = ROOT / "build" / f"{APP}.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    _draw_icon(256).save(png)
    try:  # 转换 ico 需要 Pillow 支持，失败就用默认图标
        _draw_icon(256).save(ROOT / "build" / f"{APP}.ico",
                             sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
        return ["--icon", str(ROOT / "build" / f"{APP}.ico")]
    except Exception:
        return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-icon", action="store_true")
    args = parser.parse_args()

    sep = ";" if sys.platform == "win32" else ":"
    hidden = list(COMMON_HIDDEN)
    hidden += (
        ["switchscope.ui.win_tray", "switchscope.channels.ddc_windows"]
        + WINDOWS_HIDDEN
        if sys.platform == "win32"
        else ["switchscope.ui.mac_menu", "switchscope.channels.ddc_macos"]
        + MACOS_HIDDEN
    )

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed", "--onefile", "--name", APP,
        "--add-data", f"config.example.yaml{sep}.",
    ]
    cmd += [arg for h in hidden for arg in ("--hidden-import", h)]
    if sys.platform == "darwin":
        cmd += ["--osx-bundle-identifier", "com.switchscope.app"]
    if not args.skip_icon:
        try:
            cmd += build_macos_icon() if sys.platform == "darwin" else build_windows_icon()
        except Exception as exc:
            print("Icon build failed, using default:", exc)
    cmd.append("main.py")

    # CI 的 Windows 控制台可能是 cp1252，输出一律用 ASCII
    print("Command:", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
