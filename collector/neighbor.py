"""
邻居发现模块

通过多种方式发现网络邻居：
1. LLDP (Link Layer Discovery Protocol)
2. ARP 表
3. 主动探测（临时配置 link-local IP）
"""

import re
import time
import logging
import ipaddress
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class LLDPNeighbor:
    """LLDP 邻居信息"""
    local_interface: str
    remote_system_name: str = ""
    remote_port_id: str = ""
    remote_port_desc: str = ""
    remote_mac: str = ""
    remote_mgmt_ip: str = ""

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


@dataclass
class ARPEntry:
    """ARP 表项"""
    ip_address: str
    mac_address: str
    interface: str
    state: str = ""  # REACHABLE, STALE, DELAY, etc.

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


@dataclass
class NeighborInfo:
    """邻居信息汇总"""
    local_interface: str
    discovery_method: str  # lldp, arp, probe
    remote_mac: str = ""
    remote_host: str = ""
    remote_interface: str = ""
    remote_ip: str = ""
    bidirectional: bool = False  # 是否双向确认

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class NeighborDiscovery:
    """邻居发现器"""

    # Link-local 地址范围（169.254.0.0/16）
    LINK_LOCAL_BASE = "169.254"

    def __init__(self, ssh_client, host_id: int = 0):
        """
        初始化邻居发现器

        Args:
            ssh_client: SSH 客户端
            host_id: 主机标识符（用于生成唯一的 link-local IP）
        """
        self.ssh = ssh_client
        self.host_id = host_id

    def discover_lldp(self, interfaces: Optional[List[str]] = None) -> Dict[str, LLDPNeighbor]:
        """
        通过 LLDP 发现邻居

        Args:
            interfaces: 指定接口列表，None 表示所有接口

        Returns:
            接口名到 LLDP 邻居的映射
        """
        neighbors = {}

        # 检查 lldpd 是否运行
        check_cmd = "which lldpcli 2>/dev/null && lldpcli show neighbors 2>/dev/null"
        output = self.ssh.execute(check_cmd)

        if not output.strip() or 'command not found' in output.lower():
            logger.info("LLDP not available or no neighbors found")
            return neighbors

        # 解析 LLDP 邻居信息
        neighbors = self._parse_lldp_output(output, interfaces)

        return neighbors

    def _parse_lldp_output(self, output: str,
                           interfaces: Optional[List[str]] = None) -> Dict[str, LLDPNeighbor]:
        """解析 lldpcli 输出"""
        neighbors = {}
        current_interface = None
        current_neighbor = None

        for line in output.split('\n'):
            line = line.strip()

            # 检测接口
            iface_match = re.match(r'Interface:\s*(\S+),', line)
            if iface_match:
                if current_neighbor and current_interface:
                    neighbors[current_interface] = current_neighbor

                current_interface = iface_match.group(1)
                if interfaces and current_interface not in interfaces:
                    current_interface = None
                    current_neighbor = None
                    continue

                current_neighbor = LLDPNeighbor(local_interface=current_interface)
                continue

            if not current_neighbor:
                continue

            # 解析邻居属性
            if line.startswith('SysName:'):
                current_neighbor.remote_system_name = line.split(':', 1)[1].strip()
            elif line.startswith('PortID:'):
                current_neighbor.remote_port_id = line.split(':', 1)[1].strip()
            elif line.startswith('PortDescr:'):
                current_neighbor.remote_port_desc = line.split(':', 1)[1].strip()
            elif line.startswith('MgmtIP:'):
                current_neighbor.remote_mgmt_ip = line.split(':', 1)[1].strip()

        # 保存最后一个
        if current_neighbor and current_interface:
            neighbors[current_interface] = current_neighbor

        return neighbors

    def discover_arp(self, interfaces: Optional[List[str]] = None) -> Dict[str, List[ARPEntry]]:
        """
        从 ARP 表发现邻居

        Args:
            interfaces: 指定接口列表

        Returns:
            接口名到 ARP 表项列表的映射
        """
        entries: Dict[str, List[ARPEntry]] = {}

        # 获取 ARP 表
        cmd = "ip neigh show"
        output = self.ssh.execute(cmd)

        for line in output.strip().split('\n'):
            if not line.strip():
                continue

            parts = line.split()
            if len(parts) < 4:
                continue

            ip = parts[0]
            iface = None
            mac = None
            state = ""

            for i, part in enumerate(parts):
                if part == 'dev' and i + 1 < len(parts):
                    iface = parts[i + 1]
                elif part == 'lladdr' and i + 1 < len(parts):
                    mac = parts[i + 1]
                elif part in ['REACHABLE', 'STALE', 'DELAY', 'PROBE', 'FAILED', 'PERMANENT']:
                    state = part

            if iface and mac:
                if interfaces and iface not in interfaces:
                    continue

                entry = ARPEntry(
                    ip_address=ip,
                    mac_address=mac.lower(),
                    interface=iface,
                    state=state
                )

                if iface not in entries:
                    entries[iface] = []
                entries[iface].append(entry)

        return entries

    def generate_link_local_ip(self, interface_index: int) -> str:
        """
        为接口生成唯一的 link-local IP

        使用 host_id 和 interface_index 生成唯一 IP
        格式: 169.254.<host_id>.<interface_index>
        """
        # 确保在有效范围内 (1-254)
        third_octet = (self.host_id % 254) + 1
        fourth_octet = (interface_index % 254) + 1

        return f"{self.LINK_LOCAL_BASE}.{third_octet}.{fourth_octet}"

    def probe_interface(self, interface: str, interface_index: int,
                        probe_range: str = "169.254.0.0/16",
                        timeout: float = 2.0) -> List[Tuple[str, str]]:
        """
        主动探测接口的邻居

        通过临时配置 link-local IP 并发送 ARP 请求来探测邻居

        Args:
            interface: 接口名称
            interface_index: 接口索引（用于生成 IP）
            probe_range: 探测范围
            timeout: 超时时间

        Returns:
            发现的邻居列表 [(ip, mac), ...]
        """
        neighbors = []
        temp_ip = self.generate_link_local_ip(interface_index)

        try:
            # 临时添加 link-local 地址
            add_cmd = f"ip addr add {temp_ip}/16 dev {interface} 2>/dev/null"
            self.ssh.execute(add_cmd)

            # 确保接口 up
            up_cmd = f"ip link set {interface} up 2>/dev/null"
            self.ssh.execute(up_cmd)

            # 等待接口就绪
            time.sleep(0.5)

            # 发送 ARP 探测
            # 扫描同网段可能的邻居
            for third in range(1, 10):  # 假设最多 9 台主机
                for fourth in range(1, 10):  # 每台最多 9 个接口
                    if third == (self.host_id % 254) + 1 and fourth == (interface_index % 254) + 1:
                        continue  # 跳过自己

                    target_ip = f"{self.LINK_LOCAL_BASE}.{third}.{fourth}"
                    arping_cmd = f"arping -I {interface} -c 1 -w 1 {target_ip} 2>/dev/null"
                    output = self.ssh.execute(arping_cmd)

                    # 解析响应
                    mac_match = re.search(r'\[([0-9a-fA-F:]+)\]', output)
                    if mac_match and 'Received 1 response' in output:
                        neighbors.append((target_ip, mac_match.group(1).lower()))

        except Exception as e:
            logger.error(f"Probe failed for {interface}: {e}")
        finally:
            # 清理临时 IP
            del_cmd = f"ip addr del {temp_ip}/16 dev {interface} 2>/dev/null"
            self.ssh.execute(del_cmd)

        return neighbors

    def discover_all(self, interfaces: List[str],
                     use_lldp: bool = True,
                     use_arp: bool = True,
                     use_probe: bool = False) -> Dict[str, List[NeighborInfo]]:
        """
        使用所有可用方法发现邻居

        Args:
            interfaces: 要发现的接口列表
            use_lldp: 是否使用 LLDP
            use_arp: 是否使用 ARP
            use_probe: 是否使用主动探测

        Returns:
            接口名到邻居信息列表的映射
        """
        all_neighbors: Dict[str, List[NeighborInfo]] = {iface: [] for iface in interfaces}

        # LLDP 发现
        if use_lldp:
            lldp_neighbors = self.discover_lldp(interfaces)
            for iface, neighbor in lldp_neighbors.items():
                info = NeighborInfo(
                    local_interface=iface,
                    discovery_method='lldp',
                    remote_mac=neighbor.remote_mac,
                    remote_host=neighbor.remote_system_name,
                    remote_interface=neighbor.remote_port_id or neighbor.remote_port_desc,
                    remote_ip=neighbor.remote_mgmt_ip
                )
                all_neighbors[iface].append(info)

        # ARP 发现
        if use_arp:
            arp_entries = self.discover_arp(interfaces)
            for iface, entries in arp_entries.items():
                for entry in entries:
                    # 检查是否已存在（通过 MAC 匹配）
                    exists = any(
                        n.remote_mac == entry.mac_address
                        for n in all_neighbors.get(iface, [])
                    )
                    if not exists:
                        info = NeighborInfo(
                            local_interface=iface,
                            discovery_method='arp',
                            remote_mac=entry.mac_address,
                            remote_ip=entry.ip_address
                        )
                        all_neighbors[iface].append(info)

        # 主动探测
        if use_probe:
            for idx, iface in enumerate(interfaces):
                probe_results = self.probe_interface(iface, idx)
                for ip, mac in probe_results:
                    # 检查是否已存在
                    exists = any(
                        n.remote_mac == mac
                        for n in all_neighbors.get(iface, [])
                    )
                    if not exists:
                        info = NeighborInfo(
                            local_interface=iface,
                            discovery_method='probe',
                            remote_mac=mac,
                            remote_ip=ip
                        )
                        all_neighbors[iface].append(info)

        return all_neighbors
