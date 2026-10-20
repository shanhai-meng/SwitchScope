"""SwitchScope：单显示器下 Mac ↔ Windows 快速切换。

核心思路：让「切信号源」这件事回到软件层面——
Mac 和 Windows 各跑一个小常驻程序，注册同一个全局热键，
按下即把显示器切到对方的输入源。
"""

__version__ = "0.3.0"

__all__ = ["__version__"]
