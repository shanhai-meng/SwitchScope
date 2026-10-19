"""局域网发现：找出本机所在的私有网段，并发探测指定端口。"""
from __future__ import annotations

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor
from typing import Callable


def local_private_subnets() -> list[str]:
    """返回本机所有私有 IPv4 网段，如 ['192.168.88']。"""
    nets: list[str] = []
    seen: set[str] = set()

    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        ip = info[4][0]
        if ip.startswith("127.") or ip.startswith("169.254."):
            continue
        try:
            parsed = ipaddress.IPv4Address(ip)
        except ValueError:
            continue
        if not parsed.is_private:
            continue
        net = ".".join(ip.split(".")[:3])
        if net not in seen:
            seen.add(net)
            nets.append(net)

    if not nets:
        # 兜底：直接读接口地址表
        try:
            import subprocess  # noqa: PLC0415

            out = subprocess.run(
                ["ifconfig"], capture_output=True, text=True, check=False
            ).stdout
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("inet ") and "127.0.0.1" not in line:
                    ip = line.split()[1]
                    net = ".".join(ip.split(".")[:3])
                    if net not in seen:
                        seen.add(net)
                        nets.append(net)
        except Exception:  # pragma: no cover - 极端环境
            pass
    return nets


def candidate_hosts() -> list[str]:
    """本网段内所有可能的主机地址（排除本机自己）。"""
    hosts: list[str] = []
    mine = set()
    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        mine.add(info[4][0])
    for net in local_private_subnets():
        hosts.extend(f"{net}.{i}" for i in range(1, 255) if f"{net}.{i}" not in mine)
    return hosts


def _reachable(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def scan_port(
    port: int,
    timeout: float = 0.5,
    workers: int = 256,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[str]:
    """并发扫描网段内开放 port 的主机。"""
    hosts = candidate_hosts()
    if not hosts:
        return []
    live: list[str] = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = ex.map(lambda h: (h, _reachable(h, port, timeout)), hosts)
        for host, ok in results:
            done += 1
            if on_progress and done % 32 == 0:
                on_progress(done, len(hosts))
            if ok:
                live.append(host)
    if on_progress:
        on_progress(len(hosts), len(hosts))
    return live
