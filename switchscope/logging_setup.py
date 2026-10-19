"""日志初始化：同时写文件与 stderr。"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_NAME = "SwitchScope"


def log_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData/Roaming"))
        return (Path(base) / APP_NAME / "logs")
    else:
        base = Path.home() / ".local/share"
    return base / APP_NAME / "logs"


def setup_logging(verbose: bool = False) -> logging.Logger:
    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    log_file = directory / "switchscope.log"

    logger = logging.getLogger("switchscope")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_file, maxBytes=512 * 1024, backupCount=2, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(fmt)
    stream.setLevel(logging.DEBUG if verbose else logging.WARNING)
    logger.addHandler(stream)

    logger.debug("日志目录: %s", directory)
    return logger
