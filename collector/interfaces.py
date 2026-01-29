"""
网络接口信息采集模块

通过 SSH 远程采集主机的网络接口信息，包括：
- 接口名称
- MAC 地址
- IP 地址
- 链路状态（up/down）
- 速率与双工模式
"""

import re
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class InterfaceInfo:
    """网络接口信息"""
    name: str
    mac: str = ""
    state: str = "unknown"  # up, down, unknown
    mtu: int = 0
    speed: str = ""  # e.g., "1000Mb/s", "10Gb/s"
    duplex: str = ""  # full, half, unknown
    driver: str = ""
    ipv4_addresses: List[str] = field(default_factory=list)
    ipv6_addresses: List[str] = field(default_factory=list)
    link_detected: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class InterfaceCollector:
    """网络接口信息采集器"""

    def __init__(self, ssh_client):
        """
        初始化采集器

        Args:
            ssh_client: SSH 客户端，需要实现 execute(cmd) 方法
        """
        self.ssh = ssh_client

    def collect(self, exclude_patterns: Optional[List[str]] = None) -> Dict[str, InterfaceInfo]:
        """
        采集所有网络接口信息

        Args:
            exclude_patterns: 要排除的接口名称正则模式列表

        Returns:
            接口名到接口信息的映射
        """
        interfaces = {}

        # 获取接口列表
        interface_names = self._get_interface_names()

        # 过滤排除的接口
        if exclude_patterns:
            interface_names = self._filter_interfaces(interface_names, exclude_patterns)

        # 采集每个接口的详细信息
        for name in interface_names:
            try:
                info = self._collect_interface_info(name)
                interfaces[name] = info
            except Exception as e:
                logger.warning(f"Failed to collect info for interface {name}: {e}")
                interfaces[name] = InterfaceInfo(name=name)

        return interfaces

    def _get_interface_names(self) -> List[str]:
        """获取所有网络接口名称"""
        # 使用 ip link show 获取接口列表
        cmd = "ip -o link show | awk -F': ' '{print $2}' | cut -d'@' -f1"
        output = self.ssh.execute(cmd)

        names = []
        for line in output.strip().split('\n'):
            name = line.strip()
            if name:
                names.append(name)

        return names

    def _filter_interfaces(self, names: List[str], patterns: List[str]) -> List[str]:
        """根据正则模式过滤接口"""
        filtered = []
        compiled_patterns = [re.compile(p) for p in patterns]

        for name in names:
            exclude = False
            for pattern in compiled_patterns:
                if pattern.match(name):
                    exclude = True
                    break
            if not exclude:
                filtered.append(name)

        return filtered

    def _collect_interface_info(self, name: str) -> InterfaceInfo:
        """采集单个接口的详细信息"""
        info = InterfaceInfo(name=name)

        # 获取基本信息（MAC, state, MTU）
        self._collect_basic_info(info)

        # 获取 IP 地址
        self._collect_ip_addresses(info)

        # 获取 ethtool 信息（速率、双工、驱动）
        self._collect_ethtool_info(info)

        return info

    def _collect_basic_info(self, info: InterfaceInfo):
        """采集接口基本信息"""
        cmd = f"ip -o link show {info.name}"
        output = self.ssh.execute(cmd)

        # 解析 MAC 地址
        mac_match = re.search(r'link/ether\s+([0-9a-fA-F:]+)', output)
        if mac_match:
            info.mac = mac_match.group(1).lower()

        # 解析状态
        if 'state UP' in output:
            info.state = 'up'
        elif 'state DOWN' in output:
            info.state = 'down'
        else:
            # 尝试从 flags 判断
            if '<UP,' in output or ',UP>' in output or ',UP,' in output:
                info.state = 'up'
            else:
                info.state = 'down'

        # 解析 MTU
        mtu_match = re.search(r'mtu\s+(\d+)', output)
        if mtu_match:
            info.mtu = int(mtu_match.group(1))

    def _collect_ip_addresses(self, info: InterfaceInfo):
        """采集接口 IP 地址"""
        # IPv4 地址
        cmd = f"ip -4 -o addr show {info.name} | awk '{{print $4}}'"
        output = self.ssh.execute(cmd)
        for line in output.strip().split('\n'):
            addr = line.strip()
            if addr:
                info.ipv4_addresses.append(addr)

        # IPv6 地址
        cmd = f"ip -6 -o addr show {info.name} | awk '{{print $4}}'"
        output = self.ssh.execute(cmd)
        for line in output.strip().split('\n'):
            addr = line.strip()
            if addr and not addr.startswith('fe80::'):  # 排除 link-local
                info.ipv6_addresses.append(addr)

    def _collect_ethtool_info(self, info: InterfaceInfo):
        """采集 ethtool 信息"""
        # 获取链路状态和速率
        cmd = f"ethtool {info.name} 2>/dev/null"
        output = self.ssh.execute(cmd)

        # 解析速率
        speed_match = re.search(r'Speed:\s*(\S+)', output)
        if speed_match:
            info.speed = speed_match.group(1)

        # 解析双工模式
        duplex_match = re.search(r'Duplex:\s*(\S+)', output)
        if duplex_match:
            info.duplex = duplex_match.group(1).lower()

        # 解析链路检测
        link_match = re.search(r'Link detected:\s*(\S+)', output)
        if link_match:
            info.link_detected = link_match.group(1).lower() == 'yes'

        # 获取驱动信息
        cmd = f"ethtool -i {info.name} 2>/dev/null | grep driver"
        output = self.ssh.execute(cmd)
        driver_match = re.search(r'driver:\s*(\S+)', output)
        if driver_match:
            info.driver = driver_match.group(1)
