"""
链路状态采集模块

采集网络接口的链路层状态信息，包括：
- 物理链路状态
- 载波检测
- 统计信息
- 错误计数
"""

import re
import logging
from typing import Dict, Optional, Any
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class LinkStats:
    """链路统计信息"""
    rx_bytes: int = 0
    rx_packets: int = 0
    rx_errors: int = 0
    rx_dropped: int = 0
    tx_bytes: int = 0
    tx_packets: int = 0
    tx_errors: int = 0
    tx_dropped: int = 0

    def to_dict(self) -> Dict[str, int]:
        return asdict(self)


@dataclass
class LinkState:
    """链路状态信息"""
    interface: str
    carrier: bool = False  # 载波检测
    operstate: str = "unknown"  # up, down, unknown
    link_detected: bool = False
    speed: str = ""
    duplex: str = ""
    autoneg: str = ""  # on, off
    stats: LinkStats = field(default_factory=LinkStats)

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['stats'] = self.stats.to_dict()
        return result


class LinkStateCollector:
    """链路状态采集器"""

    def __init__(self, ssh_client):
        """
        初始化采集器

        Args:
            ssh_client: SSH 客户端
        """
        self.ssh = ssh_client

    def collect(self, interfaces: list) -> Dict[str, LinkState]:
        """
        采集指定接口的链路状态

        Args:
            interfaces: 接口名称列表

        Returns:
            接口名到链路状态的映射
        """
        states = {}

        for iface in interfaces:
            try:
                state = self._collect_link_state(iface)
                states[iface] = state
            except Exception as e:
                logger.warning(f"Failed to collect link state for {iface}: {e}")
                states[iface] = LinkState(interface=iface)

        return states

    def _collect_link_state(self, interface: str) -> LinkState:
        """采集单个接口的链路状态"""
        state = LinkState(interface=interface)

        # 获取 operstate
        self._collect_operstate(state)

        # 获取 carrier 状态
        self._collect_carrier(state)

        # 获取 ethtool 链路信息
        self._collect_ethtool_link(state)

        # 获取统计信息
        self._collect_stats(state)

        return state

    def _collect_operstate(self, state: LinkState):
        """采集操作状态"""
        cmd = f"cat /sys/class/net/{state.interface}/operstate 2>/dev/null"
        output = self.ssh.execute(cmd).strip()

        if output in ['up', 'down', 'unknown', 'dormant', 'notpresent',
                      'lowerlayerdown', 'testing']:
            state.operstate = output

    def _collect_carrier(self, state: LinkState):
        """采集载波状态"""
        cmd = f"cat /sys/class/net/{state.interface}/carrier 2>/dev/null"
        output = self.ssh.execute(cmd).strip()

        try:
            state.carrier = int(output) == 1
        except ValueError:
            state.carrier = False

    def _collect_ethtool_link(self, state: LinkState):
        """采集 ethtool 链路信息"""
        cmd = f"ethtool {state.interface} 2>/dev/null"
        output = self.ssh.execute(cmd)

        # 解析速率
        speed_match = re.search(r'Speed:\s*(\S+)', output)
        if speed_match:
            state.speed = speed_match.group(1)

        # 解析双工
        duplex_match = re.search(r'Duplex:\s*(\S+)', output)
        if duplex_match:
            state.duplex = duplex_match.group(1).lower()

        # 解析自动协商
        autoneg_match = re.search(r'Auto-negotiation:\s*(\S+)', output)
        if autoneg_match:
            state.autoneg = autoneg_match.group(1).lower()

        # 解析链路检测
        link_match = re.search(r'Link detected:\s*(\S+)', output)
        if link_match:
            state.link_detected = link_match.group(1).lower() == 'yes'

    def _collect_stats(self, state: LinkState):
        """采集接口统计信息"""
        # 使用 /sys/class/net 获取统计信息
        stats_path = f"/sys/class/net/{state.interface}/statistics"

        stats_map = {
            'rx_bytes': 'rx_bytes',
            'rx_packets': 'rx_packets',
            'rx_errors': 'rx_errors',
            'rx_dropped': 'rx_dropped',
            'tx_bytes': 'tx_bytes',
            'tx_packets': 'tx_packets',
            'tx_errors': 'tx_errors',
            'tx_dropped': 'tx_dropped',
        }

        for stat_file, attr in stats_map.items():
            cmd = f"cat {stats_path}/{stat_file} 2>/dev/null"
            output = self.ssh.execute(cmd).strip()
            try:
                setattr(state.stats, attr, int(output))
            except ValueError:
                pass

    def check_link_health(self, state: LinkState) -> Dict[str, Any]:
        """
        检查链路健康状态

        Returns:
            包含健康检查结果的字典
        """
        health = {
            'interface': state.interface,
            'healthy': True,
            'issues': []
        }

        # 检查链路是否检测到
        if not state.link_detected and not state.carrier:
            health['healthy'] = False
            health['issues'].append('No link detected')

        # 检查操作状态
        if state.operstate == 'down':
            health['healthy'] = False
            health['issues'].append('Interface is administratively down')

        # 检查错误计数
        if state.stats.rx_errors > 0:
            health['issues'].append(f'RX errors: {state.stats.rx_errors}')

        if state.stats.tx_errors > 0:
            health['issues'].append(f'TX errors: {state.stats.tx_errors}')

        if state.stats.rx_dropped > 0:
            health['issues'].append(f'RX dropped: {state.stats.rx_dropped}')

        if state.stats.tx_dropped > 0:
            health['issues'].append(f'TX dropped: {state.stats.tx_dropped}')

        return health
